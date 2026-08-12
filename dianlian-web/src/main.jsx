import React from "react";
import { createRoot } from "react-dom/client";
import { DATA_SOURCE_MODE, resolveDataSourceMode } from "./dataSources/index.js";
import "./styles.css";

async function loadApplication(mode) {
  if (mode === DATA_SOURCE_MODE.API) {
    const [{ ApiPortalApp }, { ApiPortalProvider }] = await Promise.all([
      import("./apiPortal/ApiPortalApp.jsx"),
      import("./apiPortal/ApiPortalProvider.jsx"),
    ]);
    return (
      <ApiPortalProvider>
        <ApiPortalApp />
      </ApiPortalProvider>
    );
  }

  const [{ App }, { PrototypeProvider }] = await Promise.all([
    import("./App.jsx"),
    import("./state/prototypeStore.jsx"),
  ]);
  return (
    <PrototypeProvider>
      <App />
    </PrototypeProvider>
  );
}

async function bootstrap() {
  const application = await loadApplication(resolveDataSourceMode());
  createRoot(document.getElementById("root")).render(<React.StrictMode>{application}</React.StrictMode>);
}

bootstrap();
