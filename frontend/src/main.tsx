import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MsalProvider } from "@azure/msal-react";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";
import { router } from "./app/router";
import { queryClient } from "./app/queryClient";
import { msal } from "./auth/msal";
import "./styles.css";

await msal.initialize();
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MsalProvider instance={msal}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </MsalProvider>
  </StrictMode>,
);
