import { useEffect, useRef, useState, useCallback } from 'react'
import { getToken } from '@/api/client'

interface UseWebSocketOptions {
  onMessage?: (data: any) => void
  onError?: (error: Event) => void
  onClose?: () => void
  reconnect?: boolean
  reconnectInterval?: number
}

export function useWebSocket(url: string, options: UseWebSocketOptions = {}) {
  const { onMessage, onError, onClose, reconnect = true, reconnectInterval = 5000 } = options
  
  const [isConnected, setIsConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const connect = useCallback(() => {
    const token = getToken()
    const wsUrl = token ? `${url}?token=${token}` : url
    
    wsRef.current = new WebSocket(wsUrl)

    wsRef.current.onopen = () => {
      setIsConnected(true)
    }

    wsRef.current.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        onMessage?.(data)
      } catch {
        onMessage?.(event.data)
      }
    }

    wsRef.current.onerror = (error) => {
      onError?.(error)
    }

    wsRef.current.onclose = () => {
      setIsConnected(false)
      onClose?.()
      
      if (reconnect) {
        reconnectTimeoutRef.current = setTimeout(connect, reconnectInterval)
      }
    }
  }, [url, onMessage, onError, onClose, reconnect, reconnectInterval])

  useEffect(() => {
    connect()

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      wsRef.current?.close()
    }
  }, [connect])

  const send = useCallback((data: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(typeof data === 'string' ? data : JSON.stringify(data))
    }
  }, [])

  return { isConnected, send }
}
