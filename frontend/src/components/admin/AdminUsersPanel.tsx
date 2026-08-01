import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { adminApi, AdminUser } from "@/api/admin"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { AlertDialog } from "@/components/ui/alert-dialog"
import { Search, Shield, ShieldOff, Trash2, Users } from "lucide-react"

export function AdminUsersPanel() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState("")
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null)
  const [banTarget, setBanTarget] = useState<AdminUser | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const { data: users = [], isLoading } = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => adminApi.listUsers(0, 200),
  })

  const updateUser = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { role?: string } }) =>
      adminApi.updateUser(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] })
      setActionError(null)
    },
    onError: (e: Error) => setActionError(e.message),
  })

  const deleteUser = useMutation({
    mutationFn: (id: number) => adminApi.deleteUser(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] })
      setDeleteTarget(null)
      setActionError(null)
    },
    onError: (e: Error) => setActionError(e.message),
  })

  const banUser = useMutation({
    mutationFn: (id: number) => adminApi.banUser(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] })
      setBanTarget(null)
      setActionError(null)
    },
    onError: (e: Error) => setActionError(e.message),
  })

  const unbanUser = useMutation({
    mutationFn: (id: number) => adminApi.unbanUser(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] })
      setActionError(null)
    },
    onError: (e: Error) => setActionError(e.message),
  })

  const filteredUsers = users.filter(
    (u) =>
      u.username.toLowerCase().includes(search.toLowerCase()) ||
      u.email.toLowerCase().includes(search.toLowerCase())
  )

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-full max-w-sm" />
        <Card>
          <CardContent className="p-0">
            <div className="space-y-0">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex items-center gap-4 p-4 border-b last:border-b-0">
                  <Skeleton className="h-5 w-24" />
                  <Skeleton className="h-5 w-40" />
                  <Skeleton className="h-5 w-16" />
                  <Skeleton className="h-5 w-16" />
                  <Skeleton className="h-5 w-28" />
                  <div className="ml-auto flex gap-2">
                    <Skeleton className="h-8 w-16" />
                    <Skeleton className="h-8 w-16" />
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {actionError && <p className="text-sm text-destructive">{actionError}</p>}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">User Management</h2>
        <Badge variant="outline" className="gap-1">
          <Users className="h-3 w-3" />
          {users.length} users
        </Badge>
      </div>

      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search by username or email..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="text-left p-3 font-medium">Username</th>
                  <th className="text-left p-3 font-medium">Email</th>
                  <th className="text-left p-3 font-medium">Role</th>
                  <th className="text-left p-3 font-medium">Status</th>
                  <th className="text-left p-3 font-medium">Created</th>
                  <th className="text-left p-3 font-medium">Last Login</th>
                  <th className="text-right p-3 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredUsers.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="text-center p-8 text-muted-foreground">
                      No users found
                    </td>
                  </tr>
                ) : (
                  filteredUsers.map((user) => (
                    <tr key={user.id} className="border-b last:border-b-0 hover:bg-muted/30">
                      <td className="p-3 font-medium">{user.username}</td>
                      <td className="p-3 text-muted-foreground">{user.email}</td>
                      <td className="p-3">
                        <select
                          className="rounded-md border bg-background px-2 py-1 text-xs"
                          value={user.role}
                          onChange={(e) =>
                            updateUser.mutate({ id: user.id, data: { role: e.target.value } })
                          }
                        >
                          <option value="admin">admin</option>
                          <option value="user">user</option>
                          <option value="api_only">api_only</option>
                        </select>
                      </td>
                      <td className="p-3">
                        {user.is_active ? (
                          <Badge variant="success">Active</Badge>
                        ) : (
                          <Badge variant="destructive">Banned</Badge>
                        )}
                      </td>
                      <td className="p-3 text-muted-foreground text-xs">
                        {new Date(user.created_at).toLocaleDateString()}
                      </td>
                      <td className="p-3 text-muted-foreground text-xs">
                        {user.last_login
                          ? new Date(user.last_login).toLocaleDateString()
                          : "Never"}
                      </td>
                      <td className="p-3">
                        <div className="flex justify-end gap-1">
                          {user.is_active ? (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 text-xs"
                              onClick={() => setBanTarget(user)}
                            >
                              <ShieldOff className="h-3 w-3 mr-1" />
                              Ban
                            </Button>
                          ) : (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 text-xs"
                              onClick={() => unbanUser.mutate(user.id)}
                              disabled={unbanUser.isPending}
                            >
                              <Shield className="h-3 w-3 mr-1" />
                              Unban
                            </Button>
                          )}
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs text-red-500 hover:text-red-600"
                            onClick={() => setDeleteTarget(user)}
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="Delete User"
        description={`Are you sure you want to delete user "${deleteTarget?.username}"? This action cannot be undone.`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => deleteTarget && deleteUser.mutate(deleteTarget.id)}
        isLoading={deleteUser.isPending}
      />

      <AlertDialog
        open={!!banTarget}
        onOpenChange={(open) => !open && setBanTarget(null)}
        title="Ban User"
        description={`Are you sure you want to ban "${banTarget?.username}"? They will lose access to the platform.`}
        confirmLabel="Ban User"
        variant="destructive"
        onConfirm={() => banTarget && banUser.mutate(banTarget.id)}
        isLoading={banUser.isPending}
      />
    </div>
  )
}
