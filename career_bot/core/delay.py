import math
import random
import time
import hashlib
import os
import contextlib

_BASE_DELAYS = {
    'load_index': (1.16, 14.69, 5.26),
    'load_career': (0.62, 7.64, 2.56),
    'pre_single_mode': (1.80, 25.95, 2.03),
    'start_career': (1.58, 6.23, 1.98),
    'start_session': (0.62, 4.55, 1.06),
    'pre_signup': (0.62, 4.55, 1.06),
    'signup': (0.62, 4.55, 1.06),
    'check_event': (1.11, 3.90, 1.88),
    'continue': (0.96, 4.82, 3.05),
    'exec_command': (2.86, 17.68, 4.82),
    'finish_career': (3.05, 15.49, 3.54),
    'gain_skills': (7.02, 99.37, 54.62),
    'read_info': (1.16, 14.69, 5.26),
    'recovery_trainer_point': (0.62, 4.55, 1.06),
    'multi_item_exchange': (4.20, 13.79, 8.29),
    'multi_item_use': (2.99, 9.87, 5.67),
    'minigame_end': (1.11, 3.90, 1.88),
    'race_end': (1.85, 3.90, 2.01),
    'race_entry': (0.73, 4.94, 0.78),
    'change_running_style': (0.73, 4.94, 0.78),
    'reserve_race': (2.78, 9.26, 4.90),
    'race_out': (2.20, 9.91, 3.79),
    'race_start': (1.93, 10.36, 3.46),
}

import threading

# NOTE: anchored to career_bot/ (this file's PARENT package), not core/ -- the persisted timing DNA
# predates the core/ move and must keep being read from its original location.
_dna_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.timing_dna')
if not os.path.exists(_dna_path):
    with open(_dna_path, 'w') as f:
        f.write(str(random.randint(1000000, 9999999)))

with open(_dna_path, 'r') as f:
    _dna_seed = int(f.read().strip())

# These stay module-level globals on purpose: the Web UI toggles them at runtime
# (see set_turn_delay/get_turn_delay in main.py) and they apply to every account.
# CAREER PACING, in minutes (Web UI: CAREER (MIN)). Each career draws a target length in
# [CAREER_MINUTES_MIN, CAREER_MINUTES_MAX], and the pause before every turn is whatever is left of that
# budget after the play itself, spread over the turns still to come (TimingDNA.career_pause). A fixed
# pause per turn made the length follow the workload instead: 7-11 s a turn gave MANT careers ~17 min
# but busy Grand Live careers 23-24 min (2026-10-16). NO CD skips the pause.
CAREER_MINUTES_MIN = 15.0
CAREER_MINUTES_MAX = 16.0
CAREER_MINUTES_RESTORE_MIN = 15.0
CAREER_MINUTES_RESTORE_MAX = 16.0
GLOBAL_DELAYS_DISABLED = False
CAREER_TURNS = 78               # a career's last turn; one that ends early (a failed goal) is just shorter
PLAY_SECONDS_PER_TURN = 6.0     # prior for the play itself (no-pause careers: MANT ~5 s, Grand Live ~9 s)
PRIOR_WEIGHT_TURNS = 6          # ...worth this many turns of the career's own measured pace
RECENT_TURNS = 8                # the last turns' play also counts, so a career that gets busier late
                                # (race blocks, Senior events, skill buys) stops pausing in time
MAX_TURN_PAUSE = 90.0           # no single pause is longer than this, whatever the budget says

# Floor applied to every paced call while the "NO CD" kill-switch is ON.
#
# With the switch on, simulate_delay used to return 0.0 -- and so did the 0.14s inter-call floor in
# UmaClient.call, because that goes through dna_sleep -> TimingDNA.sleep, which is itself gated on
# GLOBAL_DELAYS_DISABLED. Net effect: literally zero spacing between requests.
#
# This is NOT humanization -- a couple of milliseconds fools nothing, and it is not a substitute for
# turning the kill-switch off. It only stops the bot firing back-to-back calls with no gap at all.
#
# MEASURED, don't trust the nominal value: time.sleep() cannot resolve finer than the WINDOWS TIMER
# TICK, which is global and which the running game itself raises to 1 ms. On this box (py3.10/win32):
#     nominal      idle system      game running
#     0.0001s        15.9 ms          1.98 ms
#     0.0010s        15.5 ms          1.96 ms
#     0.0100s        15.2 ms         10.02 ms
# So ~1-2 ms is the real floor -- anything below 0.001 lands in the same place -- and the value only
# behaves as written while the game holds the timer at 1 ms. Cost here: ~1.9s per 1,000-call career
# (0.01 cost ~9.9s).
#
# 0 = no sleep at all (the `if dt:` guard below skips it): back-to-back requests with zero spacing,
# the original pre-floor behaviour. Set deliberately for an A/B against 0.0001.
NO_CD_MIN_DELAY = 0.0

# Per-action ("button press") delay scale. 1.0 = realistic human pacing,
# >1 = slower, <1 = faster (0.5 = 2x faster). Set to 0.5 to speed up the
# delays-ON (human-like) mode while KEEPING the per-action variation/jitter that
# avoids a robotic fingerprint. Only affects simulate_delay, NOT the turn delay,
# and it's fully bypassed anyway when the "NO CD" kill-switch is on.
ACTION_DELAY_SCALE = 0.5


class TimingDNA:
    """A self-contained, thread-safe "timing personality".

    Each account gets its own instance (seeded from its viewer_id) so two
    accounts never share an identical timing fingerprint, and two runner
    threads never touch the same RNG state at the same time.
    """

    _registry = {}
    _registry_lock = threading.Lock()

    def __init__(self, seed):
        self.seed = int(seed)
        self.lock = threading.RLock()
        self.rng = random.Random(self.seed)
        r = self.rng
        # Persona is derived in this exact draw order so the default instance
        # reproduces the historical single-account timing stream byte-for-byte.
        self.sigma = r.uniform(0.45, 0.75)
        self.speed_shift = r.uniform(0.92, 1.08)
        self.distraction_chance = r.uniform(0.015, 0.065)
        self.distraction_min = r.uniform(1.5, 3.5)
        self.distraction_max = r.uniform(7.0, 14.0)
        self.endpoint_shifts = {ep: r.uniform(0.85, 1.15) for ep in _BASE_DELAYS}

    @classmethod
    def for_account(cls, viewer_id):
        """Return the stable, distinct personality for a given account.

        The seed mixes the per-install seed with the viewer_id, so the same
        account always gets the same rhythm while different accounts diverge.
        """
        key = int(viewer_id or 0)
        with cls._registry_lock:
            dna = cls._registry.get(key)
            if dna is None:
                mixed = hashlib.sha256(f"{_dna_seed}:{key}".encode()).hexdigest()
                dna = cls(int(mixed[:12], 16))
                cls._registry[key] = dna
            return dna

    # ---- thread-safe RNG primitives ----
    def uniform(self, a, b):
        with self.lock:
            return self.rng.uniform(a, b)

    def gauss(self, mean, stddev):
        with self.lock:
            return self.rng.gauss(mean, stddev)

    def randint(self, a, b):
        with self.lock:
            return self.rng.randint(a, b)

    def _lognorm(self, mu, sigma):
        with self.lock:
            return self.rng.lognormvariate(mu, sigma)

    def _chance(self):
        with self.lock:
            return self.rng.random()

    # ---- sleeps ----
    def sleep(self, min_val, max_val, mean=None, stddev=None):
        if GLOBAL_DELAYS_DISABLED:
            return 0.0
        if mean is not None and stddev is not None:
            dt = max(min_val, min(max_val, self.gauss(mean, stddev)))
        else:
            dt = self.uniform(min_val, max_val)
        time.sleep(dt)
        return dt

    def jittered_sleep(self, seconds, spread=0.3):
        """Sleep around `seconds` with +/- `spread` random jitter so two retries
        never wait for an identical duration (an obvious bot fingerprint)."""
        if GLOBAL_DELAYS_DISABLED:
            return 0.0
        seconds = max(0.0, float(seconds))
        spread = min(0.95, max(0.0, float(spread)))
        dt = max(0.0, self.uniform(seconds * (1.0 - spread), seconds * (1.0 + spread)))
        time.sleep(dt)
        return dt

    def backoff_sleep(self, attempt, base=1.0, cap=15.0, factor=2.0):
        """Exponential backoff with "equal jitter": grows with `attempt` up to
        `cap`, always at least half the exponential target, never identical.

        Deliberately NOT gated on GLOBAL_DELAYS_DISABLED: this is only ever used
        for SERVER-error retries (208 busy, HTTP failures, recovery), where the
        server is explicitly telling us to slow down. The delay kill-switch turns
        off humanization pacing, not obedience -- zero-sleep retry hammering is
        exactly the pattern that gets accounts throttled/flagged."""
        attempt = max(0, int(attempt))
        base = max(0.0, float(base))
        cap = max(base, float(cap))
        target = min(cap, base * (factor ** attempt))
        half = target / 2.0
        dt = min(cap, max(0.0, half + self.uniform(0.0, half)))
        time.sleep(dt)
        return dt

    def simulate_delay(self, endpoint, client=None):
        if GLOBAL_DELAYS_DISABLED:
            dt = max(0.0, NO_CD_MIN_DELAY)
            if dt:
                time.sleep(dt)
            print(f"Endpoint: {endpoint} | Delay: {dt:.4f}s", flush=True)
            return dt

        if endpoint not in _BASE_DELAYS:
            target_delay = 0.3 * self.speed_shift
            mu = math.log(target_delay) - (self.sigma ** 2) / 2.0
            dt = self._lognorm(mu, self.sigma)
            dt = max(0.08, min(1.2, dt))
        else:
            real_min, real_max, real_avg = _BASE_DELAYS[endpoint]
            ep_shift = self.endpoint_shifts[endpoint]
            target_delay = real_avg * self.speed_shift * ep_shift
            shifted_min = real_min * self.speed_shift * ep_shift
            shifted_max = real_max * self.speed_shift * ep_shift
            mu = math.log(target_delay) - (self.sigma ** 2) / 2.0
            dt = self._lognorm(mu, self.sigma)
            dt = max(shifted_min, min(shifted_max, dt))

        if self._chance() < self.distraction_chance:
            dt += self.uniform(self.distraction_min, self.distraction_max)

        dt *= ACTION_DELAY_SCALE

        print(f"Endpoint: {endpoint} | Delay: {dt:.3f}s", flush=True)

        if client is not None and hasattr(client, '_last_raw_call_ts'):
            elapsed = time.time() - client._last_raw_call_ts
            actual_sleep = dt - elapsed
            if actual_sleep > 0:
                time.sleep(actual_sleep)
        else:
            time.sleep(dt)
        return dt

    def career_pause(self, pace, turn, now=None):
        """Seconds to pause before `turn` so the career lands on pace["target"] seconds.

        This run's budget is the target times the share of the career still to play (a career resumed
        at turn 59 gets 20/78 of it). Pause = (budget left - expected play for the turns left) / turns
        left. The expected play per turn is the larger of this career's average pace (blended with
        PLAY_SECONDS_PER_TURN) and its last RECENT_TURNS turns -- so a busy career pauses less, a light
        one more, and one that gets busier late stops pausing in time. A career slower than its target
        just gets no pause. Jitter is mean-preserving and the budget is re-solved every turn."""
        now = time.monotonic() if now is None else now
        turn = int(turn)
        turns_left = max(1, CAREER_TURNS - turn + 1)
        budget = pace["target"] * max(1, CAREER_TURNS - pace["start_turn"] + 1) / CAREER_TURNS
        elapsed = now - pace["t0"]
        done = max(0, turn - pace["start_turn"])
        played = max(0.0, elapsed - pace["slept"])
        recent = pace.setdefault("recent", [])
        if pace.get("mark") is not None:            # play of the turn(s) since the last pause
            recent.append(max(0.0, (now - pace["mark"]) - pace.get("mark_pause", 0.0)))
            del recent[:-RECENT_TURNS]
        per_turn = (PLAY_SECONDS_PER_TURN * PRIOR_WEIGHT_TURNS + played) / (PRIOR_WEIGHT_TURNS + done)
        if recent:
            per_turn = max(per_turn, sum(recent) / len(recent))
        dt = (budget - elapsed - per_turn * turns_left) / turns_left
        pause = 0.0
        if dt > 0:
            sigma = 0.35 * self.sigma
            pause = min(MAX_TURN_PAUSE, self._lognorm(math.log(dt) - sigma ** 2 / 2.0, sigma))
        pace["mark"], pace["mark_pause"] = now, pause
        return pause

    def simulate_turn_delay(self, should_abort=None, seconds=None):
        """The pause before a new turn (`seconds`, from career_pause). NO CD keeps only the tiny floor.
        Sleeps in 1 s slices so Stop (should_abort) ends it at once. Returns the seconds slept."""
        if GLOBAL_DELAYS_DISABLED:
            dt = max(0.0, NO_CD_MIN_DELAY)
            if dt:
                time.sleep(dt)
            print(f"Endpoint: turn_delay | Delay: {dt:.4f}s", flush=True)
            return dt
        dt = max(0.0, float(seconds or 0.0))
        print(f"Endpoint: turn_delay | Delay: {dt:.3f}s", flush=True)
        start = time.monotonic()
        end = start + dt
        while (left := end - time.monotonic()) > 0:
            if callable(should_abort) and should_abort():
                break
            time.sleep(min(1.0, left))
        return time.monotonic() - start


# The default personality (seeded from .timing_dna) preserves the historical
# single-account behavior. All bare module-level helpers route here unless a
# per-account DNA is bound to the current thread via use_dna().
_default_dna = TimingDNA(_dna_seed)

_active = threading.local()


def use_dna(dna):
    """Bind `dna` as the active personality for the current thread.

    Each account's runner runs in its own thread, so binding once makes every
    subsequent bare delay call in that thread use the right account's timing.
    """
    _active.dna = dna


def current_dna():
    return getattr(_active, "dna", None) or _default_dna


def simulate_delay(endpoint, client=None):
    return current_dna().simulate_delay(endpoint, client)


def simulate_turn_delay(should_abort=None, seconds=None):
    return current_dna().simulate_turn_delay(should_abort, seconds)


def dna_randint(min_val, max_val):
    return current_dna().randint(min_val, max_val)


def dna_sleep(min_val, max_val, mean=None, stddev=None):
    return current_dna().sleep(min_val, max_val, mean, stddev)


def server_sleep(min_val, max_val):
    """A wait that ALWAYS happens, even with GLOBAL_DELAYS_DISABLED on. For
    server-mandated pauses (205 stale retries, throttle walls, loop spacing
    between careers) -- the kill-switch only skips humanization pacing, it must
    never turn structural waits into a zero-delay hammer."""
    import random as _random
    dt = max(0.0, _random.uniform(float(min_val), float(max_val)))
    time.sleep(dt)
    return dt


def dna_uniform(min_val, max_val):
    return current_dna().uniform(min_val, max_val)


def dna_gauss(mean, stddev):
    return current_dna().gauss(mean, stddev)


def jittered_sleep(seconds, spread=0.3):
    return current_dna().jittered_sleep(seconds, spread)


def backoff_sleep(attempt, base=1.0, cap=15.0, factor=2.0):
    return current_dna().backoff_sleep(attempt, base=base, cap=cap, factor=factor)


class GateKeeper:
    def __init__(self, client, dna=None):
        super().__setattr__('_client', client)
        raw_call = getattr(client, '_gatekeeper_raw_call', None)
        if raw_call is None:
            raw_call = client.call
            setattr(client, '_gatekeeper_raw_call', raw_call)
        super().__setattr__('_raw_call', raw_call)
        if dna is None:
            viewer_id = getattr(client, 'viewer_id', 0)
            dna = TimingDNA.for_account(viewer_id) if viewer_id else _default_dna
        super().__setattr__('_dna', dna)
        use_dna(dna)
        client.call = self._paced_call

    def begin_career_pacing(self):
        """A new career's clock (runner.start): draw its target length; the first paced turn sets t0."""
        lo = max(0.0, float(CAREER_MINUTES_MIN))
        hi = max(lo, float(CAREER_MINUTES_MAX))
        super().__setattr__('_pace', {"target": self._dna.uniform(lo, hi) * 60.0, "t0": None,
                                      "start_turn": None, "slept": 0.0, "last_turn": 0})

    def wait_turn_delay(self, turn=None):
        """Pause before `turn` (once per turn) so the whole career lands on its target length."""
        use_dna(self._dna)
        pace = self.__dict__.get('_pace')
        if pace is None:
            self.begin_career_pacing()
            pace = self.__dict__['_pace']
        turn = int(turn or 0)
        if turn <= 0 or turn <= pace["last_turn"]:
            return 0.0      # a turn-less screen (Grand Live concert) or a turn already paced
        if pace["t0"] is None:
            pace["t0"], pace["start_turn"] = time.monotonic(), turn
        seconds = self._dna.career_pause(pace, turn)
        # The runner wires should_abort to its Stop flag, so Stop ends a long pause at once.
        pace["slept"] += self._dna.simulate_turn_delay(getattr(self._client, "should_abort", None), seconds)
        pace["last_turn"] = turn
        return seconds

    def wait_complex_delay(self):
        pass

    def __setattr__(self, name, value):
        if name in ('_client', '_raw_call', '_dna'):
            super().__setattr__(name, value)
        else:
            setattr(self._client, name, value)

    def _pacing_name(self, ep):
        path_map = {
            'load/index': 'load_index',
            'read_info/index': 'read_info',
            'pre_single_mode/index': 'pre_single_mode',
            'tool/start_session': 'start_session',
            'tool/pre_signup': 'pre_signup',
            'tool/signup': 'signup',
            'user/recovery_trainer_point': 'recovery_trainer_point',
            'single_mode_free/start': 'start_career',
            'single_mode_free/check_event': 'check_event',
            'single_mode_free/exec_command': 'exec_command',
            'single_mode_free/read_info': 'load_index',
            'single_mode_free/pre': 'pre_single_mode',
            'single_mode_free/race_continue': 'continue',
            'single_mode_free/continue': 'continue',
            'single_mode_free/gain_skills': 'gain_skills',
            'single_mode_free/multi_item_exchange': 'multi_item_exchange',
            'single_mode_free/multi_item_use': 'multi_item_use',
            'single_mode_free/minigame_end': 'minigame_end',
            'single_mode_free/race_end': 'race_end',
            'single_mode_free/race_entry': 'race_entry',
            'single_mode_free/change_running_style': 'change_running_style',
            'single_mode_free/reserve_race': 'reserve_race',
            'single_mode_free/race_out': 'race_out',
            'single_mode_free/race_start': 'race_start',
            'single_mode_free/load': 'load_career',
            'single_mode_free/finish': 'finish_career'
        }
        return path_map.get(ep, ep.split('/')[-1])

    def _paced_call(self, ep, *args, **kwargs):
        use_dna(self._dna)
        self._dna.simulate_delay(self._pacing_name(ep), self._client)
        return self._raw_call(ep, *args, **kwargs)

    @contextlib.contextmanager
    def unpaced(self):
        """Temporarily bypass per-call humanise pacing for an INTERACTIVE UI call the
        user is actively waiting on (e.g. the REFRESH button's re-login) -- never the
        autonomous grind. Pacing is restored on exit even if the body raises.

        SAFETY: this flips the shared client's `call` for the duration, so the caller
        MUST guarantee no career-runner thread is touching this client concurrently.
        refresh_session() enforces exactly that (it refuses while a runner is active)."""
        self._client.call = self._raw_call
        try:
            yield self._client
        finally:
            self._client.call = self._paced_call

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        return attr
