import { useState } from "react";
import {
  IconBell,
  IconBuildingSkyscraper,
  IconChevronDown,
  IconCoinYuan,
  IconLayoutGrid,
  IconListCheck,
  IconLayoutDashboard,
  IconMessages,
  IconRobot,
  IconSettings,
  IconShieldLock,
  IconLogout,
} from "@tabler/icons-react";
import { BrandLogo } from "./BrandLogo.jsx";

const navigation = [
  { key: "office", label: "组织大厅", href: "/office", icon: IconLayoutGrid },
  { key: "messages", label: "消息", href: "/messages", icon: IconMessages, optional: "messages" },
  { key: "employees", label: "数字员工", href: "/employees", icon: IconRobot },
  { key: "tasks", label: "当前任务", href: "/tasks", icon: IconListCheck },
  { key: "points", label: "智点明细", href: "/me/points", icon: IconCoinYuan, optional: "points" },
];

export function PortalHeader({
  activeKey,
  onNavigate,
  pointBalance = 12450,
  tenantName = "星海会展集团",
  userName = "陈露",
  userAvatar = "/assets/employees/quotation-specialist.png",
  userRoleLabel = "企业管理员",
  notificationCount = 6,
  showAdminLinks = false,
  showEnterpriseLink = showAdminLinks,
  showPlatformLink = showAdminLinks,
  showMessages = false,
  messagePath = "/messages",
  onLogout = null,
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <>
      <header className="portal-header">
        <div className="portal-brand-cluster">
          <button className="brand-button" type="button" onClick={() => onNavigate("/office")}>
            <BrandLogo />
          </button>
          <span className="portal-product-name">企业数字办公大厅</span>
        </div>

        <div className="tenant-context" aria-label={`当前企业：${tenantName}`}>
          <IconBuildingSkyscraper size={17} stroke={1.8} />
          <span><small>当前企业</small><strong>{tenantName}</strong></span>
        </div>

        <div className="portal-header__actions">
          {pointBalance !== null && pointBalance !== undefined ? (
            <button className="points-pill" type="button" onClick={() => onNavigate("/me/points")}>
              <IconCoinYuan size={18} stroke={1.9} />
              <span><small>可用智点</small><strong>{pointBalance.toLocaleString("zh-CN")}</strong></span>
            </button>
          ) : null}
          <span className="icon-button has-dot" aria-label={`通知${notificationCount > 0 ? `，${notificationCount}条` : ""}`}>
            <IconBell size={20} stroke={1.8} />
            {notificationCount > 0 ? <span className="notification-dot">{notificationCount}</span> : null}
          </span>
          <div className="account-menu">
            <button className="avatar-button" type="button" aria-label={`${userName}的账户菜单`} aria-expanded={menuOpen} aria-controls="portal-account-menu" onClick={() => setMenuOpen((open) => !open)}>
              <img src={userAvatar} alt={userName} />
              <span><strong>{userName}</strong><small>{userRoleLabel}</small></span>
              <IconChevronDown size={15} stroke={1.8} />
            </button>
            {menuOpen && (
              <div className="account-menu__panel" id="portal-account-menu">
                <div className="account-menu__identity">
                  <strong>{userName}</strong>
                  <span>{userRoleLabel}</span>
                </div>
                {showEnterpriseLink || showPlatformLink ? (
                  <>
                    {showEnterpriseLink ? (
                      <button type="button" onClick={() => { setMenuOpen(false); onNavigate("/enterprise/agents"); }}>
                        <IconLayoutDashboard size={17} />
                        企业管理中心
                      </button>
                    ) : null}
                    {showPlatformLink ? (
                      <button type="button" onClick={() => { setMenuOpen(false); onNavigate("/platform/overview"); }}>
                        <IconShieldLock size={17} />
                        平台运营中心
                      </button>
                    ) : null}
                  </>
                ) : null}
                <button type="button">
                  <IconSettings size={17} />
                  个人设置
                </button>
                {typeof onLogout === "function" ? (
                  <button type="button" onClick={() => { setMenuOpen(false); onLogout(); }}>
                    <IconLogout size={17} />
                    退出登录
                  </button>
                ) : null}
              </div>
            )}
          </div>
        </div>
      </header>

      <nav className="portal-side-nav" aria-label="企业工作入口">
        {navigation
          .filter((item) => item.optional !== "messages" || showMessages)
          .filter((item) => item.optional !== "points" || pointBalance !== null && pointBalance !== undefined)
          .map((item) => {
            const Icon = item.icon;
            const href = item.key === "messages" ? messagePath : item.href;
            return (
              <button
                className={activeKey === item.key ? "is-active" : ""}
                key={item.key}
                type="button"
                aria-current={activeKey === item.key ? "page" : undefined}
                onClick={() => onNavigate(href)}
              >
                <Icon size={20} stroke={1.7} />
                <span>{item.label}</span>
              </button>
            );
          })}
      </nav>
    </>
  );
}
