import * as React from 'react'
import { cn } from '@/lib/utils'

interface TabsContextValue {
  value: string
  onValueChange: (value: string) => void
  baseId: string
}

const TabsContext = React.createContext<TabsContextValue | undefined>(undefined)

interface TabsProps extends React.HTMLAttributes<HTMLDivElement> {
  value: string
  onValueChange: (value: string) => void
}

const Tabs = React.forwardRef<HTMLDivElement, TabsProps>(
  ({ className, value, onValueChange, ...props }, ref) => {
    const baseId = React.useId().replace(/:/g, '')
    return (
      <TabsContext.Provider value={{ value, onValueChange, baseId }}>
        <div ref={ref} className={cn('', className)} {...props} />
      </TabsContext.Provider>
    )
  }
)
Tabs.displayName = 'Tabs'

const TabsList = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      role="tablist"
      className={cn(
        'inline-flex h-10 items-center justify-start rounded-md bg-muted p-1 text-muted-foreground overflow-x-auto scrollbar-thin',
        className
      )}
      {...props}
    />
  )
)
TabsList.displayName = 'TabsList'

interface TabsTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  value: string
}

const TabsTrigger = React.forwardRef<HTMLButtonElement, TabsTriggerProps>(
  ({ className, value, ...props }, ref) => {
    const context = React.useContext(TabsContext)
    if (!context) throw new Error('TabsTrigger must be used within Tabs')

    const { value: activeValue, onValueChange, baseId } = context
    const isActive = activeValue === value
    const triggerId = `${baseId}-tab-${value}`
    const panelId = `${baseId}-panel-${value}`

    const onKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
      const tabs = Array.from(
        event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]') ?? []
      )
      if (tabs.length === 0) return
      const currentIndex = tabs.indexOf(event.currentTarget)
      let nextIndex = currentIndex
      if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % tabs.length
      else if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + tabs.length) % tabs.length
      else if (event.key === 'Home') nextIndex = 0
      else if (event.key === 'End') nextIndex = tabs.length - 1
      else return

      event.preventDefault()
      const next = tabs[nextIndex]
      next?.focus()
      onValueChange(next?.dataset.value ?? value)
    }

    return (
      <button
        ref={ref}
        role="tab"
        id={triggerId}
        aria-selected={isActive}
        aria-controls={panelId}
        tabIndex={isActive ? 0 : -1}
        data-value={value}
        className={cn(
          'inline-flex items-center justify-center whitespace-nowrap rounded-sm px-2 sm:px-3 py-1.5 text-xs sm:text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 shrink-0',
          isActive && 'bg-background text-foreground shadow-sm',
          className
        )}
        onClick={() => context.onValueChange(value)}
        onKeyDown={onKeyDown}
        {...props}
      />
    )
  }
)
TabsTrigger.displayName = 'TabsTrigger'

interface TabsContentProps extends React.HTMLAttributes<HTMLDivElement> {
  value: string
}

const TabsContent = React.forwardRef<HTMLDivElement, TabsContentProps>(
  ({ className, value, ...props }, ref) => {
    const context = React.useContext(TabsContext)
    if (!context) throw new Error('TabsContent must be used within Tabs')
    
    if (context.value !== value) return null
    
    return (
      <div
        ref={ref}
        role="tabpanel"
        id={`${context.baseId}-panel-${value}`}
        aria-labelledby={`${context.baseId}-tab-${value}`}
        tabIndex={0}
        className={cn(
          'mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
          className
        )}
        {...props}
      />
    )
  }
)
TabsContent.displayName = 'TabsContent'

export { Tabs, TabsList, TabsTrigger, TabsContent }
