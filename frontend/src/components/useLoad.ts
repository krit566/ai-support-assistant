import { useCallback, useEffect, useState } from "react";

// Load data for a page: { data, error, loading, reload }. Ignores results that arrive after the page changed.
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const load = useCallback(fn, deps);

  useEffect(() => {
    let live = true;
    setLoading(true);
    load()
      .then((d) => live && (setData(d), setError("")))
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : "Could not load"))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [load, tick]);

  return { data, error, loading, reload: () => setTick((t) => t + 1), setData };
}
