import { createBrowserRouter } from "react-router-dom";
import { ProtectedRoute } from "../auth/ProtectedRoute";
import { RoleGuard } from "../auth/RoleGuard";
import { AppShell } from "../components/layout/AppShell";
import { AdminRulesPage } from "../pages/AdminRulesPage";
import { ClassificationReviewPage } from "../pages/ClassificationReviewPage";
import { DashboardPage } from "../pages/DashboardPage";
import { DocumentsPage } from "../pages/DocumentsPage";
import { DraftEditorPage } from "../pages/DraftEditorPage";
import { DraftQueuePage } from "../pages/DraftQueuePage";
import { EvaluationPage } from "../pages/EvaluationPage";
import { ReviewQueuePage } from "../pages/ReviewQueuePage";
import { SendApprovalQueuePage } from "../pages/SendApprovalQueuePage";
import { CommunicationStatusPage } from "../pages/CommunicationStatusPage";
import { TaskBoardPage } from "../pages/TaskBoardPage";
import { TaskDetailPage } from "../pages/TaskDetailPage";
import { UnauthorizedPage } from "../pages/UnauthorizedPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: (
      <ProtectedRoute>
        <AppShell />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "reviews", element: <ReviewQueuePage /> },
      { path: "reviews/:id", element: <ClassificationReviewPage /> },
      { path: "tasks", element: <TaskBoardPage /> },
      { path: "tasks/:id", element: <TaskDetailPage /> },
      { path: "documents", element: <DocumentsPage /> },
      {
        path: "communications/drafts",
        element: (
          <RoleGuard role="Licensing.Reviewer">
            <DraftQueuePage />
          </RoleGuard>
        ),
      },
      {
        path: "communications/drafts/:id",
        element: (
          <RoleGuard role="Licensing.Reviewer">
            <DraftEditorPage />
          </RoleGuard>
        ),
      },
      {
        path: "communications/approvals",
        element: (
          <RoleGuard role="Licensing.Sender">
            <SendApprovalQueuePage />
          </RoleGuard>
        ),
      },
      { path: "communications/status", element: <CommunicationStatusPage /> },
      { path: "admin/rules", element: <AdminRulesPage /> },
      { path: "evaluation", element: <EvaluationPage /> },
      { path: "unauthorized", element: <UnauthorizedPage /> },
    ],
  },
]);
