import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import "./styles.css";
import { captureSessionFromUrl } from "./api";
import { Layout } from "./pages/Layout";

captureSessionFromUrl();
import { DashboardPage } from "./pages/Dashboard";
import { ProspectQueuePage } from "./pages/ProspectQueue";
import { TakeoffsPage } from "./pages/Takeoffs";
import { TakeoffReviewPage } from "./pages/TakeoffReview";
import { QuotesPage } from "./pages/Quotes";
import { QuoteBuilderPage } from "./pages/QuoteBuilder";
import { AdminPage } from "./pages/Admin";

const rootRoute = createRootRoute({ component: Layout });

export const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: DashboardPage,
});

export const prospectsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/prospects",
  component: ProspectQueuePage,
});

export const takeoffsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/takeoffs",
  component: TakeoffsPage,
});

export const takeoffReviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/takeoffs/$takeoffId",
  component: TakeoffReviewPage,
});

export const quotesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/quotes",
  component: QuotesPage,
});

export const quoteBuilderRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/quotes/$quoteId",
  component: QuoteBuilderPage,
});

export const adminRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin",
  component: AdminPage,
});

const routeTree = rootRoute.addChildren([
  dashboardRoute,
  prospectsRoute,
  takeoffsRoute,
  takeoffReviewRoute,
  quotesRoute,
  quoteBuilderRoute,
  adminRoute,
]);

const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>
);
