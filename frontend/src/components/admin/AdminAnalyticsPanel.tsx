import { useQuery } from "@tanstack/react-query"
import { adminApi } from "@/api/admin"
import { MetricsCard } from "@/components/dashboard/MetricsCard"
import { Card, CardHeader, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { formatCents } from "@/lib/utils"
import {
  Users,
  UserCheck,
  Server,
  Activity,
  Globe,
  DollarSign,
  TrendingUp,
} from "lucide-react"

function AnalyticsSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-7 w-48" />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 7 }).map((_, i) => (
          <Card key={i}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-4 w-4" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-8 w-16 mb-1" />
              <Skeleton className="h-3 w-20" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}

export function AdminAnalyticsPanel() {
  const { data: analytics, isLoading } = useQuery({
    queryKey: ["admin-analytics"],
    queryFn: adminApi.getAnalytics,
    refetchInterval: 30000,
  })

  if (isLoading || !analytics) {
    return <AnalyticsSkeleton />
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Platform Analytics</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricsCard
          title="Total Users"
          value={analytics.total_users}
          subtitle={`${analytics.active_users} active`}
          icon={Users}
        />
        <MetricsCard
          title="Active Users"
          value={analytics.active_users}
          subtitle={`${Math.round((analytics.active_users / analytics.total_users) * 100)}% of total`}
          icon={UserCheck}
          variant="success"
        />
        <MetricsCard
          title="Total Instances"
          value={analytics.total_instances}
          subtitle={`${analytics.running_instances} running`}
          icon={Server}
        />
        <MetricsCard
          title="Running Instances"
          value={analytics.running_instances}
          subtitle={`${Math.round((analytics.running_instances / Math.max(analytics.total_instances, 1)) * 100)}% utilization`}
          icon={Activity}
          variant={analytics.running_instances > 0 ? "success" : "default"}
        />
        <MetricsCard
          title="Servers Connected"
          value={analytics.total_servers}
          icon={Globe}
        />
        <MetricsCard
          title="Total Revenue"
          value={formatCents(analytics.total_revenue)}
          icon={DollarSign}
          variant="success"
        />
        <MetricsCard
          title="Signups (30d)"
          value={analytics.signups_last_30_days}
          subtitle="new registrations"
          icon={TrendingUp}
          variant={analytics.signups_last_30_days > 0 ? "success" : "default"}
        />
      </div>
    </div>
  )
}
