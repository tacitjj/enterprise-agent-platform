export function BrandLogo({ compact = false }) {
  return (
    <div className={`brand-lockup${compact ? " brand-lockup--compact" : ""}`} aria-label="点联">
      <img src="/assets/brand/dianlian-logo.png" alt="点联" />
    </div>
  );
}
