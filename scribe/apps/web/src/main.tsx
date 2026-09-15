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
import { ToastProvider } from "./components/ui";
import { applyTheme, readThemePref } from "./theme";

captureSessionFromUrl();
applyTheme(readThemePref());
import { DashboardPage } from "./pages/Dashboard";
import { ProspectQueuePage } from "./pages/ProspectQueue";
import { ProspectDetailPage } from "./pages/ProspectDetail";
import { TakeoffsPage } from "./pages/Takeoffs";
import { TakeoffReviewPage } from "./pages/TakeoffReview";
import { PagePickerPage } from "./pages/PagePicker";
import { BetaDetectPage } from "./pages/BetaDetect";
import { QuotesPage } from "./pages/Quotes";
import { QuoteBuilderPage } from "./pages/QuoteBuilder";
import { AdminPage } from "./pages/Admin";
import { SignupPage } from "./pages/Signup";
import { AccountPage } from "./pages/Account";

const rootRoute = createRootRoute({ component: Layout });

// Jobs is the app (product-plan.md §2). The pipeline dashboard is an
// operator screen, reachable from the account menu.
export const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/dashboard",
  component: DashboardPage,
});

export const jobsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: TakeoffsPage,
});

export const prospectsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/prospects",
  component: ProspectQueuePage,
});

export const prospectDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/prospects/$projectId",
  component: ProspectDetailPage,
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

// Gate 1: page selection after upload (status awaiting_pages). Gate 2 is the
// wizard below (status awaiting_boxes): mark the cabinet areas → find → build.
export const pagePickerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/takeoffs/$takeoffId/pages",
  component: PagePickerPage,
});

// The wizard: the located drawings arrive pre-boxed; the human adjusts,
// finds the cabinets, builds the takeoff. The one reading flow for PDFs.
export const betaDetectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/takeoffs/$takeoffId/detect",
  component: BetaDetectPage,
  // ?pages=1,3,5 — the Pages step hands its selection over so the wizard
  // opens straight on Draw with those pages.
  validateSearch: (search: Record<string, unknown>): { pages?: string } => ({
    pages: typeof search.pages === "string" && search.pages ? search.pages : undefined,
  }),
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
  validateSearch: (search: Record<string, unknown>): { tab?: string } => ({
    tab: typeof search.tab === "string" ? search.tab : undefined,
  }),
});

// Public: the invite link lands here (accounts-plan.md §1.2).
export const signupRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/signup",
  component: SignupPage,
  validateSearch: (search: Record<string, unknown>): { token?: string } => ({
    token: typeof search.token === "string" && search.token ? search.token : undefined,
  }),
});

export const accountRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/account",
  component: AccountPage,
});

const routeTree = rootRoute.addChildren([
  signupRoute,
  accountRoute,
  jobsRoute,
  dashboardRoute,
  prospectsRoute,
  prospectDetailRoute,
  takeoffsRoute,
  takeoffReviewRoute,
  pagePickerRoute,
  betaDetectRoute,
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
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>
);
