import Foundation

/// Single time source for the recording pipeline. Wraps `mach_absolute_time`
/// so frame timestamps and input-event timestamps live in the same domain.
enum MonotonicClock {
    private static let timebase: mach_timebase_info_data_t = {
        var info = mach_timebase_info_data_t()
        mach_timebase_info(&info)
        return info
    }()

    /// Milliseconds since boot (mach absolute time). Monotonic, not wall-clock.
    static func nowMs() -> Int64 {
        machToMs(mach_absolute_time())
    }

    /// Convert a mach absolute time tick count to milliseconds.
    static func machToMs(_ ticks: UInt64) -> Int64 {
        let nanos = ticks &* UInt64(timebase.numer) / UInt64(timebase.denom)
        return Int64(nanos / 1_000_000)
    }

    /// Wall-clock ms since epoch. Use for `started_at_ms` / `entered_at_ms` only.
    static func wallClockMs() -> Int64 {
        Int64(Date().timeIntervalSince1970 * 1000)
    }
}
