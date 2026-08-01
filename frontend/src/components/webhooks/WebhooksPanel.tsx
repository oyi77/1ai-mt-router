import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useWebhooks, CreateWebhookRequest } from '@/api/webhooks'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Webhook, RefreshCw, Trash2, Send, Plus } from 'lucide-react'

const EVENT_OPTIONS = [
  { value: 'trade.opened', label: 'Trade Opened' },
  { value: 'trade.closed', label: 'Trade Closed' },
  { value: 'trade.modified', label: 'Trade Modified' },
  { value: 'order.pending', label: 'Pending Order' },
  { value: 'position.update', label: 'Position Update' },
  { value: 'account.balance', label: 'Balance Change' },
]

// Client-side mirror of the backend SSRF guard (backend/app/services/notification_service.py).
// DNS resolution is done server-side only; here we can only reject literal hosts/IPs.
function validateWebhookUrl(url: string): string | null {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return 'Enter a valid URL'
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return 'Only http/https webhook URLs are allowed'
  }
  const host = parsed.hostname.toLowerCase()
  if (!host) return 'Webhook URL must include a host'
  if (host === 'localhost' || host === '127.0.0.1' || host === '::1' || host === '0.0.0.0') {
    return 'Webhook URL host is not allowed'
  }
  const ipv4 = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/)
  if (ipv4) {
    const parts = ipv4.slice(1).map(Number)
    if (parts.some((p) => p > 255)) return 'Webhook URL host is not allowed'
    const [a, b] = parts
    if (
      a === 127 || a === 0 || a === 10 ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) ||
      (a === 169 && b === 254)
    ) {
      return 'Webhook URL host is not allowed'
    }
    return null
  }
  if (host.includes(':')) {
    const h = host.replace(/^\[|\]$/g, '')
    if (
      h === '::1' || h === '::' || h === '0:0:0:0:0:0:0:1' ||
      h.startsWith('fe80:') || h.startsWith('fc') || h.startsWith('fd')
    ) {
      return 'Webhook URL host is not allowed'
    }
    return null
  }
  return null
}

export function WebhooksPanel() {
  const queryClient = useQueryClient()
  const { fetchWebhooks, createWebhook, deleteWebhook, testWebhook } = useWebhooks()
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [formData, setFormData] = useState<CreateWebhookRequest>({
    name: '',
    url: '',
    secret: '',
    events: [],
  })
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [testingId, setTestingId] = useState<number | null>(null)
  const [urlError, setUrlError] = useState<string | null>(null)

  const { data: webhooks = [], isLoading, refetch } = useQuery({
    queryKey: ['webhooks'],
    queryFn: fetchWebhooks,
  })

  const handleSubmit = async () => {
    const error = validateWebhookUrl(formData.url)
    if (error) {
      setUrlError(error)
      return
    }
    setIsSubmitting(true)
    try {
      await createWebhook(formData)
      setIsDialogOpen(false)
      setFormData({ name: '', url: '', secret: '', events: [] })
      queryClient.invalidateQueries({ queryKey: ['webhooks'] })
    } catch (error) {
      console.error('Failed to create webhook:', error)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDelete = async (id: number) => {
    if (confirm('Are you sure you want to delete this webhook?')) {
      try {
        await deleteWebhook(id)
        queryClient.invalidateQueries({ queryKey: ['webhooks'] })
      } catch (error) {
        console.error('Failed to delete webhook:', error)
      }
    }
  }

  const handleTest = async (id: number) => {
    setTestingId(id)
    try {
      const result = await testWebhook(id)
      alert(result.status === 'success' 
        ? `Test successful! Response code: ${result.response_code}`
        : `Test failed: ${result.message}`)
    } catch (error) {
      console.error('Failed to test webhook:', error)
    } finally {
      setTestingId(null)
    }
  }

  const toggleEvent = (event: string) => {
    setFormData(prev => ({
      ...prev,
      events: prev.events.includes(event)
        ? prev.events.filter(e => e !== event)
        : [...prev.events, event]
    }))
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Webhook className="h-5 w-5" />
            Webhooks
          </CardTitle>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Refresh
            </Button>
            <Button size="sm" onClick={() => setIsDialogOpen(true)}>
              <Plus className="h-4 w-4 mr-2" />
              Add Webhook
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {[1, 2].map((i) => (
                <div key={i} className="flex items-center justify-between p-4 border rounded-lg">
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-5 w-32" />
                    <Skeleton className="h-4 w-48" />
                    <div className="flex gap-1">
                      <Skeleton className="h-5 w-20" />
                      <Skeleton className="h-5 w-20" />
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Skeleton className="h-8 w-8" />
                    <Skeleton className="h-8 w-8" />
                  </div>
                </div>
              ))}
            </div>
          ) : webhooks.length === 0 ? (
            <div className="text-center py-8 border rounded-lg">
              <Webhook className="h-10 w-10 mx-auto text-muted-foreground mb-3" />
              <p className="text-muted-foreground">No webhooks configured</p>
              <Button className="mt-4" onClick={() => setIsDialogOpen(true)}>
                <Plus className="h-4 w-4 mr-2" />
                Add Webhook
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              {webhooks.map((webhook) => (
                <div key={webhook.id} className="flex items-center justify-between p-4 border rounded-lg">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{webhook.name}</span>
                      <Badge variant={webhook.is_active ? 'default' : 'secondary'}>
                        {webhook.is_active ? 'Active' : 'Inactive'}
                      </Badge>
                    </div>
                    <p className="text-sm text-muted-foreground truncate">{webhook.url}</p>
                    <div className="flex gap-1 mt-2 flex-wrap">
                      {webhook.events.map((event) => (
                        <Badge key={event} variant="outline" className="text-xs">
                          {event}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  <div className="flex gap-2 ml-4">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleTest(webhook.id)}
                      disabled={testingId === webhook.id}
                    >
                      <Send className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleDelete(webhook.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Webhook</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="name">Name</Label>
              <Input
                id="name"
                placeholder="My Webhook"
                value={formData.name}
                onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
              />
            </div>
            <div>
              <Label htmlFor="url">URL</Label>
              <Input
                id="url"
                placeholder="https://example.com/webhook"
                value={formData.url}
                onChange={(e) => {
                  setFormData(prev => ({ ...prev, url: e.target.value }))
                  setUrlError(null)
                }}
              />
              {urlError && <p className="text-sm text-destructive mt-1">{urlError}</p>}
            </div>
            <div>
              <Label htmlFor="secret">Secret (optional)</Label>
              <Input
                id="secret"
                type="password"
                placeholder="Your webhook secret"
                value={formData.secret || ''}
                onChange={(e) => setFormData(prev => ({ ...prev, secret: e.target.value }))}
              />
            </div>
            <div>
              <Label>Events</Label>
              <div className="flex flex-wrap gap-2 mt-2">
                {EVENT_OPTIONS.map((option) => (
                  <Button
                    key={option.value}
                    variant={formData.events.includes(option.value) ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => toggleEvent(option.value)}
                  >
                    {option.label}
                  </Button>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={!formData.name || !formData.url || formData.events.length === 0 || isSubmitting}
            >
              {isSubmitting ? 'Creating...' : 'Create'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}