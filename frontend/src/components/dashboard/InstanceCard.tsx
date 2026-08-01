import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { Instance } from '@/api/instances'
import { Play, Square, RotateCcw, Trash2, Monitor, Terminal, Loader2 } from 'lucide-react'

interface InstanceCardProps {
  instance: Instance
  isActionLoading?: boolean
  onStart?: () => void
  onStop?: () => void
  onRestart?: () => void
  onDelete?: () => void
  onVNC?: () => void
  onLogs?: () => void
  onClick?: () => void
  className?: string
}

export function InstanceCard({
  instance,
  isActionLoading = false,
  onStart,
  onStop,
  onRestart,
  onDelete,
  onVNC,
  onLogs,
  onClick,
  className,
}: InstanceCardProps) {
  const statusVariant = {
    running: 'success',
    stopped: 'destructive',
    restarting: 'warning',
    created: 'secondary',
    exited: 'destructive',
    paused: 'warning',
    dead: 'destructive',
  } as const

  const statusDotClass = {
    running: 'status-running',
    stopped: 'status-stopped',
    restarting: 'status-restarting',
    created: 'bg-gray-500',
    exited: 'bg-red-500',
    paused: 'bg-amber-500',
    dead: 'bg-red-500',
  }

  return (
    <Card className={cn('', className)} onClick={onClick}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={cn('status-dot', statusDotClass[instance.status])} />
            <CardTitle className="text-lg">{instance.name}</CardTitle>
          </div>
          <Badge variant={statusVariant[instance.status]}>
            {instance.status}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground font-mono mt-1">{instance.id.substring(0, 12)}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-2" onClick={(e) => e.stopPropagation()}>
          {(instance.status === 'stopped' || instance.status === 'exited') && onStart && (
            <Button size="sm" variant="outline" onClick={onStart} disabled={isActionLoading}>
              {isActionLoading ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Play className="h-4 w-4 mr-1" />}
              Start
            </Button>
          )}
          {instance.status === 'running' && onStop && (
            <Button size="sm" variant="outline" onClick={onStop} disabled={isActionLoading}>
              {isActionLoading ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Square className="h-4 w-4 mr-1" />}
              Stop
            </Button>
          )}
          {instance.status === 'running' && onRestart && (
            <Button size="sm" variant="outline" onClick={onRestart} disabled={isActionLoading}>
              {isActionLoading ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <RotateCcw className="h-4 w-4 mr-1" />}
              Restart
            </Button>
          )}
          {instance.vnc_port && onVNC && (
            <Button size="sm" variant="outline" onClick={onVNC}>
              <Monitor className="h-4 w-4 mr-1" />
              VNC
            </Button>
          )}
          {onLogs && (
            <Button size="sm" variant="outline" onClick={onLogs}>
              <Terminal className="h-4 w-4 mr-1" />
              Logs
            </Button>
          )}
          {onDelete && (
            <Button size="sm" variant="destructive" onClick={onDelete} disabled={isActionLoading}>
              <Trash2 className="h-4 w-4 mr-1" />
              Delete
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
