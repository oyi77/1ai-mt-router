import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { statisticsApi, TradeStatistics, SymbolStats, EquityPoint, DailySummary } from '@/api/statistics'
import { useQuery } from '@tanstack/react-query'
import { TrendingUp, Target, BarChart3, PieChart } from 'lucide-react'
import { MiniChart } from '@/components/charts/MiniChart'

interface StatisticsPanelProps {
  instanceId: string
}

export function StatisticsPanel({ instanceId }: StatisticsPanelProps) {
  const days = 30

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['stats-summary', instanceId, days],
    queryFn: () => statisticsApi.getSummary(instanceId, days),
    enabled: !!instanceId,
  })

  const { data: symbolStats, isLoading: symbolsLoading } = useQuery({
    queryKey: ['stats-symbols', instanceId, days],
    queryFn: () => statisticsApi.getSymbols(instanceId, days),
    enabled: !!instanceId,
  })

  const { data: equityCurve, isLoading: equityLoading } = useQuery({
    queryKey: ['stats-equity', instanceId, days],
    queryFn: () => statisticsApi.getEquityCurve(instanceId, days),
    enabled: !!instanceId,
  })

  if (!instanceId) {
    return (
      <Card>
        <CardContent className="py-8">
          <p className="text-center text-muted-foreground">
            Select an MT5 instance to view trading statistics
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Total Trades</CardTitle>
            <Target className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.total_trades || 0}</div>
            <p className="text-xs text-muted-foreground">
              {stats?.winning_trades || 0} wins, {stats?.losing_trades || 0} losses
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Win Rate</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.win_rate?.toFixed(1) || 0}%</div>
            <p className="text-xs text-muted-foreground">Last {days} days</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Net Profit</CardTitle>
            <BarChart3 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${(stats?.net_profit || 0) >= 0 ? 'text-green-500' : 'text-red-500'}`}>
              ${stats?.net_profit?.toFixed(2) || '0.00'}
            </div>
            <p className="text-xs text-muted-foreground">
              ${stats?.total_profit?.toFixed(0) || 0} profit / ${stats?.total_loss?.toFixed(0) || 0} loss
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium">Profit Factor</CardTitle>
            <PieChart className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats?.profit_factor?.toFixed(2) || '0.00'}</div>
            <p className="text-xs text-muted-foreground">
              Max Drawdown: ${stats?.max_drawdown?.toFixed(2) || '0.00'}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Performance Metrics</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 grid-cols-2 md:grid-cols-3">
            <div>
              <p className="text-sm text-muted-foreground">Average Win</p>
              <p className="text-lg font-semibold text-green-500">
                ${stats?.average_win?.toFixed(2) || '0.00'}
              </p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Average Loss</p>
              <p className="text-lg font-semibold text-red-500">
                ${stats?.average_loss?.toFixed(2) || '0.00'}
              </p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Largest Win</p>
              <p className="text-lg font-semibold text-green-500">
                ${stats?.largest_win?.toFixed(2) || '0.00'}
              </p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Largest Loss</p>
              <p className="text-lg font-semibold text-red-500">
                ${stats?.largest_loss?.toFixed(2) || '0.00'}
              </p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Total Profit</p>
              <p className="text-lg font-semibold text-green-500">
                ${stats?.total_profit?.toFixed(2) || '0.00'}
              </p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Total Loss</p>
              <p className="text-lg font-semibold text-red-500">
                ${stats?.total_loss?.toFixed(2) || '0.00'}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Symbol Performance</CardTitle>
        </CardHeader>
        <CardContent>
          {symbolsLoading ? (
            <p className="text-muted-foreground">Loading...</p>
          ) : (
            <div className="space-y-2">
              {symbolStats?.map((symbol) => (
                <div key={symbol.symbol} className="flex items-center justify-between p-2 border rounded">
                  <div>
                    <span className="font-medium">{symbol.symbol}</span>
                    <span className="text-muted-foreground text-sm ml-2">
                      ({symbol.trades} trades)
                    </span>
                  </div>
                  <div className="text-right">
                    <Badge variant={symbol.net_profit >= 0 ? 'default' : 'destructive'}>
                      {symbol.win_rate.toFixed(1)}% WR
                    </Badge>
                    <span className={`ml-2 ${symbol.net_profit >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                      ${symbol.net_profit.toFixed(2)}
                    </span>
                  </div>
                </div>
              ))}
              {!symbolStats?.length && (
                <p className="text-muted-foreground">No trades yet</p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Equity Curve (Last {days} Days)</CardTitle>
        </CardHeader>
        <CardContent>
          {equityLoading ? (
            <p className="text-muted-foreground">Loading...</p>
          ) : (
            <div className="border rounded bg-muted/20 p-2">
              <MiniChart
                data={(equityCurve || []).map((p) => ({ time: p.timestamp, value: p.equity }))}
                label="Equity ($)"
                color="green"
                height={240}
              />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}