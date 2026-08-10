import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-zinc-200 bg-white p-4 shadow-sm ${className}`}>
      {children}
    </div>
  );
}

export function Button({
  variant = "default",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "primary" | "danger" | "ghost";
}) {
  const styles = {
    default: "border border-zinc-300 bg-white hover:bg-zinc-100",
    primary: "bg-zinc-900 text-white hover:bg-zinc-700",
    danger: "bg-red-600 text-white hover:bg-red-500",
    ghost: "hover:bg-zinc-100",
  }[variant];
  return (
    <button
      className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
      {...props}
    />
  );
}

export function Input({
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm focus:border-zinc-500 focus:outline-none ${className}`}
      {...props}
    />
  );
}

export function Badge({
  children,
  tone = "zinc",
}: {
  children: ReactNode;
  tone?: "zinc" | "green" | "amber" | "red" | "blue";
}) {
  const tones = {
    zinc: "bg-zinc-100 text-zinc-700",
    green: "bg-green-100 text-green-800",
    amber: "bg-amber-100 text-amber-800",
    red: "bg-red-100 text-red-800",
    blue: "bg-blue-100 text-blue-800",
  }[tone];
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${tones}`}>
      {children}
    </span>
  );
}

export function PageTitle({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between">
      <h1 className="text-xl font-semibold">{children}</h1>
      {actions}
    </div>
  );
}

export function statusTone(status: string): "zinc" | "green" | "amber" | "red" | "blue" {
  switch (status) {
    case "approved":
    case "won":
    case "sent":
      return "green";
    case "review":
    case "extracted":
    case "quoting":
    case "draft":
    case "awaiting_pages":
    case "awaiting_boxes":
      return "amber";
    case "failed":
    case "lost":
      return "red";
    case "processing":
    case "new":
      return "blue";
    default:
      return "zinc";
  }
}
