import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { apiDataSource } from "../dataSources/apiDataSource.js";
import { mapOfficeSnapshotResponse } from "./adapters.js";
import { loadPortalBootstrap } from "./portalBootstrap.js";
import { createSingleFlight } from "./singleFlight.js";

const ApiPortalContext = createContext(null);

function failurePhase(error) {
  if (error?.status === 401) return "unauthenticated";
  if (error?.status === 403) return "forbidden";
  return "error";
}

export function ApiPortalProvider({ children, dataSource = apiDataSource }) {
  const mounted = useRef(false);
  const initialLoad = useRef(createSingleFlight());
  const [state, setState] = useState({
    phase: "loading-session",
    session: null,
    office: null,
    officeEtag: null,
    error: null,
  });

  const load = useCallback(() => initialLoad.current.run(async () => {
    if (!mounted.current) return;
    setState({ phase: "loading-session", session: null, office: null, officeEtag: null, error: null });
    try {
      const nextState = await loadPortalBootstrap(dataSource, {
        isActive: () => mounted.current,
        onTenantSession: (session) => {
          setState({ phase: "loading-office", session, office: null, officeEtag: null, error: null });
        },
      });
      if (nextState && mounted.current) setState(nextState);
    } catch (error) {
      if (!mounted.current) return;
      setState((current) => ({ ...current, phase: failurePhase(error), error }));
    }
  }), [dataSource]);

  useEffect(() => {
    mounted.current = true;
    load();
    return () => {
      mounted.current = false;
    };
  }, [load]);

  const refreshOffice = useCallback(async () => {
    if (!state.session || !state.office) return;
    const response = await dataSource.getOfficeSnapshot({ etag: state.officeEtag });
    if (response.notModified) return;
    setState((current) => ({
      ...current,
      office: mapOfficeSnapshotResponse(response.snapshot),
      officeEtag: response.etag,
    }));
  }, [dataSource, state.office, state.officeEtag, state.session]);

  const login = useCallback(async (credentials) => {
    await dataSource.login(credentials);
    await load();
  }, [dataSource, load]);

  const logout = useCallback(async () => {
    try {
      await dataSource.logout();
    } finally {
      setState({ phase: "unauthenticated", session: null, office: null, officeEtag: null, error: null });
    }
  }, [dataSource]);

  const value = useMemo(() => ({
    ...state,
    dataSource,
    reload: load,
    refreshOffice,
    login,
    logout,
  }), [dataSource, load, login, logout, refreshOffice, state]);

  return <ApiPortalContext.Provider value={value}>{children}</ApiPortalContext.Provider>;
}

export function useApiPortal() {
  const context = useContext(ApiPortalContext);
  if (!context) throw new Error("useApiPortal must be used inside ApiPortalProvider");
  return context;
}
