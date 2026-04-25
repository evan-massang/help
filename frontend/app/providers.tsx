"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { AlertToast } from "@/components/AlertToast";
import { HelpOverlay, KeyboardNav } from "@/components/KeyboardNav";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            staleTime: 2_000,
            retry: 1,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      {children}
      <AlertToast />
      <KeyboardNav />
      <HelpOverlay />
    </QueryClientProvider>
  );
}
