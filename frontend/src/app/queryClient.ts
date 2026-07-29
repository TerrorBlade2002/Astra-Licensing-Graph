import { QueryClient } from "@tanstack/react-query";
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 20_000,
      retry: (count, error) =>
        !(
          error instanceof Error &&
          "status" in error &&
          (error as { status: number }).status < 500
        ) && count < 2,
    },
    mutations: { retry: false },
  },
});
