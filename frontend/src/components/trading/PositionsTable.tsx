import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { AlertDialog } from "@/components/ui/alert-dialog"
import { Position } from "@/api/trading"
import { formatNumber, formatCurrency } from "@/lib/utils"
import { X, TrendingUp, TrendingDown, Settings, SplitSquareHorizontal } from "lucide-react"

interface PositionsTableProps {
  positions: Position[]
  currency?: string
  onClosePosition: (ticket: number) => void
  onModifyPosition?: (ticket: number, sl: number | null, tp: number | null) => void
  onPartialClose?: (ticket: number, volume: number) => void
  isLoading?: boolean
}

// Symbol prices vary in scale (forex ~1.08, JPY pairs ~150, gold ~2000); adapt digits to magnitude.
function formatPrice(value: number): string {
  const digits = value >= 100 ? 2 : value >= 1 ? 4 : 5
  return value.toFixed(digits)
}

export function PositionsTable({ positions, currency, onClosePosition, onModifyPosition, onPartialClose, isLoading }: PositionsTableProps) {
  const totalPnL = positions.reduce((sum, pos) => sum + pos.profit, 0)
  const [modifyDialog, setModifyDialog] = useState<{ ticket: number; sl: number | null; tp: number | null } | null>(null)
  const [partialCloseDialog, setPartialCloseDialog] = useState<{ ticket: number; volume: number } | null>(null)
  const [closeTarget, setCloseTarget] = useState<Position | null>(null)
  const [slValue, setSlValue] = useState('')
  const [tpValue, setTpValue] = useState('')
  const [partialVolume, setPartialVolume] = useState('')
  const [modifyError, setModifyError] = useState<string | null>(null)
  const [partialCloseError, setPartialCloseError] = useState<string | null>(null)

  const handleModifySubmit = () => {
    if (modifyDialog && onModifyPosition) {
      const sl = slValue ? parseFloat(slValue) : null
      const tp = tpValue ? parseFloat(tpValue) : null
      if ((sl !== null && !Number.isFinite(sl)) || (tp !== null && !Number.isFinite(tp))) {
        setModifyError('Invalid SL/TP value')
        return
      }
      onModifyPosition(modifyDialog.ticket, sl, tp)
      setModifyDialog(null)
      setSlValue('')
      setTpValue('')
      setModifyError(null)
    }
  }

  const handlePartialCloseSubmit = () => {
    if (partialCloseDialog && onPartialClose && partialVolume) {
      const volume = parseFloat(partialVolume)
      if (!Number.isFinite(volume) || volume < 0.01 || volume > partialCloseDialog.volume) {
        setPartialCloseError('Invalid volume')
        return
      }
      onPartialClose(partialCloseDialog.ticket, volume)
      setPartialCloseDialog(null)
      setPartialVolume('')
      setPartialCloseError(null)
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between flex-wrap gap-2">
        <CardTitle className="text-base sm:text-lg">
          Open Positions ({positions.length})
          <span className={`ml-2 text-lg ${totalPnL >= 0 ? 'text-green-500' : 'text-red-500'}`}>
            {totalPnL >= 0 ? '+' : ''}{formatCurrency(totalPnL, currency)}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {positions.length === 0 ? (
          <p className="text-center text-muted-foreground py-4">No open positions</p>
        ) : (
          <div className="overflow-x-auto -mx-4 sm:mx-0">
            <table className="w-full text-sm min-w-[600px]">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-2 px-2 sm:px-3">Symbol</th>
                  <th className="text-left py-2 px-2 sm:px-3">Type</th>
                  <th className="text-right py-2 px-2 sm:px-3">Volume</th>
                  <th className="text-right py-2 px-2 sm:px-3">Open Price</th>
                  <th className="text-right py-2 px-2 sm:px-3">Current</th>
                  <th className="text-right py-2 px-2 sm:px-3">P&L</th>
                  <th className="text-right py-2 px-2 sm:px-3">SL</th>
                  <th className="text-right py-2 px-2 sm:px-3">TP</th>
                  <th className="text-center py-2 px-2 sm:px-3">Action</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => (
                  <tr key={pos.ticket} className="border-b hover:bg-muted/50">
                    <td className="py-2 px-2 font-medium">{pos.symbol}</td>
                    <td className="py-2 px-2">
                      <Badge variant={pos.type === 'BUY' ? 'success' : 'destructive'}>
                        {pos.type === 'BUY' ? (
                          <TrendingUp className="h-3 w-3 mr-1" />
                        ) : (
                          <TrendingDown className="h-3 w-3 mr-1" />
                        )}
                        {pos.type}
                      </Badge>
                    </td>
                    <td className="py-2 px-2 text-right font-mono">{formatNumber(pos.volume)}</td>
                    <td className="py-2 px-2 text-right font-mono">{formatPrice(pos.open_price)}</td>
                    <td className="py-2 px-2 text-right font-mono">{formatPrice(pos.current_price)}</td>
                    <td className={`py-2 px-2 text-right font-mono ${pos.profit >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                      {pos.profit >= 0 ? '+' : ''}{formatCurrency(pos.profit, currency)}
                    </td>
                    <td className="py-2 px-2 text-right font-mono text-muted-foreground">
                      {pos.sl ? formatPrice(pos.sl) : '-'}
                    </td>
                    <td className="py-2 px-2 text-right font-mono text-muted-foreground">
                      {pos.tp ? formatPrice(pos.tp) : '-'}
                    </td>
                    <td className="py-2 px-2 text-center">
                      <div className="flex gap-1 justify-center">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setModifyError(null)
                            setModifyDialog({ ticket: pos.ticket, sl: pos.sl, tp: pos.tp })
                            setSlValue(pos.sl?.toString() || '')
                            setTpValue(pos.tp?.toString() || '')
                          }}
                          title="Modify SL/TP"
                        >
                          <Settings className="h-3 w-3" />
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setPartialCloseError(null)
                            setPartialCloseDialog({ ticket: pos.ticket, volume: pos.volume })
                          }}
                          title="Partial Close"
                        >
                          <SplitSquareHorizontal className="h-3 w-3" />
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => setCloseTarget(pos)}
                          disabled={isLoading}
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {modifyDialog && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
            <div className="bg-card p-4 sm:p-6 rounded-lg border shadow-lg w-full max-w-sm">
              <h3 className="text-lg font-semibold mb-4">Modify Position #{modifyDialog.ticket}</h3>
              <div className="space-y-4">
                <div>
                  <label className="text-sm font-medium">Stop Loss</label>
                  <Input
                    type="number"
                    step="0.00001"
                    placeholder="SL Price"
                    value={slValue}
                    onChange={(e) => setSlValue(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium">Take Profit</label>
                  <Input
                    type="number"
                    step="0.00001"
                    placeholder="TP Price"
                    value={tpValue}
                    onChange={(e) => setTpValue(e.target.value)}
                  />
                </div>
                {modifyError && <p className="text-sm text-destructive">{modifyError}</p>}
                <div className="flex flex-col sm:flex-row gap-2 sm:justify-end">
                  <Button variant="outline" onClick={() => setModifyDialog(null)} className="w-full sm:w-auto">
                    Cancel
                  </Button>
                  <Button onClick={handleModifySubmit} className="w-full sm:w-auto">
                    Save Changes
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}

        {partialCloseDialog && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
            <div className="bg-card p-4 sm:p-6 rounded-lg border shadow-lg w-full max-w-sm">
              <h3 className="text-lg font-semibold mb-4">Partial Close #{partialCloseDialog.ticket}</h3>
              <div className="space-y-4">
                <div>
                  <label className="text-sm font-medium">Volume to Close</label>
                  <Input
                    type="number"
                    step="0.01"
                    min="0.01"
                    max={partialCloseDialog.volume}
                    placeholder={`Max: ${partialCloseDialog.volume}`}
                    value={partialVolume}
                    onChange={(e) => setPartialVolume(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground mt-1">
                    Position volume: {formatNumber(partialCloseDialog.volume)}
                  </p>
                </div>
                {partialCloseError && <p className="text-sm text-destructive">{partialCloseError}</p>}
                <div className="flex flex-col sm:flex-row gap-2 sm:justify-end">
                  <Button variant="outline" onClick={() => setPartialCloseDialog(null)} className="w-full sm:w-auto">
                    Cancel
                  </Button>
                  <Button onClick={handlePartialCloseSubmit} disabled={!partialVolume} className="w-full sm:w-auto">
                    Close Partial
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Close Confirmation */}
        <AlertDialog
          open={!!closeTarget}
          onOpenChange={(open) => !open && setCloseTarget(null)}
          title="Close Position"
          description={closeTarget ? `Close ${closeTarget.symbol} (#${closeTarget.ticket})?` : ''}
          confirmLabel="Close"
          variant="destructive"
          onConfirm={() => {
            if (closeTarget) onClosePosition(closeTarget.ticket)
            setCloseTarget(null)
          }}
          isLoading={isLoading}
        />
      </CardContent>
    </Card>
  )
}
