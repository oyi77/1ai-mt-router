import * as React from "react"
import { cn } from "@/lib/utils"
import { AlertTriangle } from "lucide-react"
import { Button } from "./button"

interface AlertDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: "destructive" | "default"
  onConfirm: () => unknown
  isLoading?: boolean
}

export function AlertDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "default",
  onConfirm,
  isLoading = false,
}: AlertDialogProps) {
  React.useEffect(() => {
    if (!open || isLoading) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false)
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [open, isLoading, onOpenChange])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      onClick={() => onOpenChange(false)}
    >
      <div className="fixed inset-0 bg-black/50" />
      <div
        role="alertdialog"
        aria-modal="true"
        tabIndex={-1}
        className="relative z-50 bg-background rounded-lg border p-6 shadow-lg w-full max-w-md mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex gap-4">
          <div className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-full",
            variant === "destructive" ? "bg-red-100 dark:bg-red-900/20" : "bg-muted"
          )}>
            <AlertTriangle className={cn(
              "h-5 w-5",
              variant === "destructive" ? "text-red-600 dark:text-red-400" : "text-muted-foreground"
            )} />
          </div>
          <div className="flex-1">
            <h3 className="text-lg font-semibold">{title}</h3>
            <p className="text-sm text-muted-foreground mt-1">{description}</p>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-6">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isLoading}>
            {cancelLabel}
          </Button>
          <Button
            variant={variant === "destructive" ? "destructive" : "default"}
            onClick={async () => {
              try {
                await onConfirm()
                onOpenChange(false)
              } catch {
                // Keep the dialog open so the user can retry.
              }
            }}
            disabled={isLoading}
          >
            {isLoading ? "..." : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
