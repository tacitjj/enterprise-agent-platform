import React from "react";

const DEFAULT_COPY = Object.freeze({
  loading: ["正在连接点联办公室", "正在读取登录会话和当前企业的授权快照。"],
  unauthenticated: ["需要登录", "当前会话未登录或已经失效，请登录后重新进入。"],
  forbidden: ["无权进入当前企业", "当前账号没有访问这个企业办公室的权限。"],
  empty: ["还没有可用的数字员工", "请联系企业管理员招聘并配置员工后再开始工作。"],
  error: ["办公室暂时不可用", "真实接口请求失败，系统不会回退到演示数据。"],
  unavailable: ["该能力尚未接入真实 API", "当前切片只开放办公室、员工工作台和任务详情。"],
  "not-found": ["没有找到这条记录", "资源不存在，或当前账号没有发现它的权限。"],
});

export function ApiBoundaryState({ kind = "error", title, detail, actionLabel, onAction }) {
  const [defaultTitle, defaultDetail] = DEFAULT_COPY[kind] ?? DEFAULT_COPY.error;
  const role = kind === "loading" ? "status" : "alert";
  return React.createElement(
    "main",
    { className: `api-boundary api-boundary--${kind}`, role, "data-api-state": kind },
    React.createElement(
      "section",
      null,
      React.createElement("span", { className: "api-boundary__mark", "aria-hidden": "true" }, "点"),
      React.createElement("h1", null, title || defaultTitle),
      React.createElement("p", null, detail || defaultDetail),
      typeof onAction === "function"
        ? React.createElement("button", { type: "button", onClick: onAction }, actionLabel || "重试")
        : null,
    ),
  );
}
