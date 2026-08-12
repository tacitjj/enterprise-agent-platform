import { IconX } from "@tabler/icons-react";
import "./event-work-surface.css";

export function EventWorkSurface({
  eyebrow,
  title,
  description,
  actions = null,
  onClose,
  children,
  className = "",
}) {
  return (
    <main className={`event-work-layer ${className}`.trim()}>
      <section className="event-work-surface" aria-label={title}>
        <header className="event-work-surface__header">
          <div className="event-work-surface__title">
            {eyebrow ? <small>{eyebrow}</small> : null}
            <h1>{title}</h1>
            {description ? <p>{description}</p> : null}
          </div>
          <div className="event-work-surface__actions">
            {actions}
            {typeof onClose === "function" ? (
              <button className="event-work-surface__close" type="button" aria-label={`关闭${title}`} onClick={onClose}>
                <IconX size={19} stroke={1.8} />
              </button>
            ) : null}
          </div>
        </header>
        <div className="event-work-surface__body">{children}</div>
      </section>
    </main>
  );
}
