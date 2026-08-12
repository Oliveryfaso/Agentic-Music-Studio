import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { ImportReviewPage } from "../features/import-review/ImportReviewPage";

export function App() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 1, refetchOnWindowFocus: false },
          mutations: { retry: false },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ImportReviewPage />
    </QueryClientProvider>
  );
}
