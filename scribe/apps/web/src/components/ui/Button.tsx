import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "default" | "quiet" | "danger" | "ghost";
export type ButtonSize = "sm" | "md";

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-white border-accent hover:bg-accent-hover hover:border-accent-hover",
  default: "bg-paper text-ink border-rule hover:bg-rule-soft",
  quiet: "bg-transparent text-ink border-transparent hover:bg-rule-soft",
  ghost: "bg-transparent text-ink border-transparent hover:bg-rule-soft",
  danger: "bg-bad text-white border-bad hover:opacity-90",
};

const SIZE: Record<ButtonSize, string> = {
  sm: "px-2 py-1 text-xs gap-1",
  md: "px-3 py-1.5 text-sm gap-1.5",
};

export function Button({
  variant = "default",
  size = "md",
  loading = false,
  className = "",
  children,
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}) {
  return (
    <button
      className={`inline-flex items-center justify-center whitespace-nowrap rounded-md border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT[variant]} ${SIZE[size]} ${className}`}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && (
        <span
          aria-hidden
          className="inline-block size-3 animate-spin rounded-full border-[1.5px] border-current border-r-transparent"
        />
      )}
      {children}
    </button>
  );
}
