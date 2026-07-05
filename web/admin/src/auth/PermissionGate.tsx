import type { ReactNode } from 'react';

import { currentUser } from './authStore';

type Props = {
  permission: string;
  children: ReactNode;
  fallback?: ReactNode;
};

export function PermissionGate({ permission, children, fallback = null }: Props) {
  const user = currentUser();

  if (!user?.permissions.includes(permission)) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
}

