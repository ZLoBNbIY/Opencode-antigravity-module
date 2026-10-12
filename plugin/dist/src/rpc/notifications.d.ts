import type { RpcNotification, RpcNotificationPayload } from './protocol';
export declare function pushNotification(payload: RpcNotificationPayload, sessionId?: string): void;
export declare function drainNotifications(lastReceivedId?: number, sessionId?: string): RpcNotification[];
export declare function isTuiConnected(sessionId?: string): boolean;
export declare function resetNotificationsForTest(): void;
//# sourceMappingURL=notifications.d.ts.map