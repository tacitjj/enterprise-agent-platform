export function createSingleFlight() {
  let active = null;

  return Object.freeze({
    run(factory) {
      if (typeof factory !== "function") throw new TypeError("single-flight factory is required");
      if (active) return active;

      const work = Promise.resolve().then(factory);
      const tracked = work.finally(() => {
        if (active === tracked) active = null;
      });
      active = tracked;
      return tracked;
    },
  });
}
