import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { PortalHeader } from "../components/PortalHeader.jsx";
import { selectOfficeViewModel, selectPointViewModel, usePrototypeState } from "../state/prototypeStore.jsx";

function resolveActiveKey(pathname) {
  if (pathname.startsWith("/rooms")) return "messages";
  if (pathname.startsWith("/employees")) return "employees";
  if (pathname.startsWith("/tasks")) return "tasks";
  if (pathname.startsWith("/me/points")) return "points";
  return "office";
}

export function PortalShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const state = usePrototypeState();
  const pointAccount = selectPointViewModel(state);
  const office = selectOfficeViewModel(state);
  const messagePath = office?.rooms?.[0]?.id ? `/rooms/${office.rooms[0].id}` : null;
  const tenant = state.tenantsById[state.session.currentTenantId];
  const user = state.usersById[state.session.currentUserId];

  return (
    <div className="portal-app">
      <PortalHeader
        activeKey={resolveActiveKey(location.pathname)}
        onNavigate={navigate}
        pointBalance={pointAccount?.available ?? 0}
        tenantName={tenant?.name ?? "当前企业"}
        userName={user?.name ?? "企业成员"}
        userRoleLabel="企业成员"
        showMessages={Boolean(messagePath)}
        messagePath={messagePath ?? "/office"}
      />
      <div className="portal-workspace"><Outlet /></div>
    </div>
  );
}
