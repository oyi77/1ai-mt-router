import * as React from "react"
import { cn } from "@/lib/utils"
import { X } from "lucide-react"

interface DialogProps {
  open?: boolean
  onOpenChange?: (open: boolean) => void
  children: React.ReactNode
}

const Dialog: React.FC<DialogProps> = ({ open = false, onOpenChange, children }) => {
  const [titleId, setTitleId] = React.useState("")

  React.useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden"
    } else {
      document.body.style.overflow = ""
    }
    return () => { document.body.style.overflow = "" }
  }, [open])

  React.useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange?.(false)
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [open, onOpenChange])

  if (!open) return null

  return (
    <DialogContext.Provider value={{ onOpenChange, titleId, setTitleId }}>
      {children}
    </DialogContext.Provider>
  )
}

const DialogContext = React.createContext<{
  onOpenChange?: (open: boolean) => void
  titleId: string
  setTitleId: (id: string) => void
}>({ titleId: "", setTitleId: () => {} })

interface DialogContentProps extends React.HTMLAttributes<HTMLDivElement> {
  children?: React.ReactNode
}

const DialogContent = React.forwardRef<HTMLDivElement, DialogContentProps>(
  ({ className, children, ...props }, ref) => {
    const { onOpenChange, titleId } = React.useContext(DialogContext)

    return (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center"
        onClick={() => onOpenChange?.(false)}
      >
        <div className="fixed inset-0 bg-black/50 animate-in fade-in-0" />
          <div
          ref={ref}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId || undefined}
          tabIndex={-1}
          className={cn(
            "relative z-50 bg-background rounded-lg border p-4 sm:p-6 shadow-lg w-full max-w-lg mx-2 sm:mx-4 animate-in fade-in-0 zoom-in-95 max-h-[90vh] overflow-y-auto",
            className
          )}
          onClick={(e) => e.stopPropagation()}
          {...props}
        >
          <button
            className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
            onClick={() => onOpenChange?.(false)}
          >
            <X className="h-4 w-4" />
            <span className="sr-only">Close</span>
          </button>
          {children}
        </div>
      </div>
    )
  }
)
DialogContent.displayName = "DialogContent"

interface DialogHeaderProps extends React.HTMLAttributes<HTMLDivElement> {
  children?: React.ReactNode
}

const DialogHeader: React.FC<DialogHeaderProps> = ({ className, children, ...props }) => {
  return (
    <div className={cn("flex flex-col space-y-1.5 text-center sm:text-left mb-4", className)} {...props}>
      {children}
    </div>
  )
}

const DialogDescription: React.FC<React.HTMLAttributes<HTMLParagraphElement>> = ({ className, children, ...props }) => {
  return (
    <p className={cn("text-sm text-muted-foreground", className)} {...props}>
      {children}
    </p>
  )
}

interface DialogTitleProps extends React.HTMLAttributes<HTMLHeadingElement> {
  children?: React.ReactNode
}

const DialogTitle = React.forwardRef<HTMLHeadingElement, DialogTitleProps>(
  ({ className, children, ...props }, ref) => {
    const { setTitleId } = React.useContext(DialogContext)
    const generatedId = React.useId()
    const titleId = props.id ?? generatedId

    React.useEffect(() => {
      setTitleId(titleId)
    }, [setTitleId, titleId])

    return (
      <h2
        ref={ref}
        id={titleId}
        className={cn("text-lg font-semibold leading-none tracking-tight", className)}
        {...props}
      >
        {children}
      </h2>
    )
  }
)
DialogTitle.displayName = "DialogTitle"

interface DialogFooterProps extends React.HTMLAttributes<HTMLDivElement> {
  children?: React.ReactNode
}

const DialogFooter: React.FC<DialogFooterProps> = ({ className, children, ...props }) => {
  return (
    <div
      className={cn("flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2 mt-6", className)}
      {...props}
    >
      {children}
    </div>
  )
}

export { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter }
