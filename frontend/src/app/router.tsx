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
import { ComplianceCalendarPage } from "../pages/ComplianceCalendarPage";
import { CorrespondenceReviewPage } from "../pages/CorrespondenceReviewPage";
import { CurrentTrackerPage } from "../pages/CurrentTrackerPage";
import { ComplianceCasePage } from "../pages/ComplianceCasePage";
import { ComplianceCasesPage } from "../pages/ComplianceCasesPage";
import { DataQualityPage } from "../pages/DataQualityPage";
import { FormPreparationPage } from "../pages/FormPreparationPage";
import { InformationRegistryPage } from "../pages/InformationRegistryPage";
import { LicenseDetailPage } from "../pages/LicenseDetailPage";
import { LicenseInventoryPage } from "../pages/LicenseInventoryPage";
import { LicensingDashboardPage } from "../pages/LicensingDashboardPage";
import { MasterTrackerImportPage } from "../pages/MasterTrackerImportPage";
import { PacketBuilderPage } from "../pages/PacketBuilderPage";
import { RequirementAssessmentPage } from "../pages/RequirementAssessmentPage";
import { RequirementResultPage } from "../pages/RequirementResultPage";
import { RequirementSourcesPage } from "../pages/RequirementSourcesPage";
import { PortalDefinitionPage } from "../pages/PortalDefinitionPage";
import { PortalHandoffPage } from "../pages/PortalHandoffPage";
import { PortalRegistryPage } from "../pages/PortalRegistryPage";
import { PortalRunPage } from "../pages/PortalRunPage";
import { PortalRunQueuePage } from "../pages/PortalRunQueuePage";
import { PreSubmissionReviewPage } from "../pages/PreSubmissionReviewPage";
import { SubmissionEvidencePage } from "../pages/SubmissionEvidencePage";

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
      { path: "licensing", element: <LicensingDashboardPage /> },
      { path: "licensing/tracker", element: <CurrentTrackerPage /> },
      {
        path: "licensing/correspondence",
        element: <CorrespondenceReviewPage />,
      },
      { path: "licensing/licenses", element: <LicenseInventoryPage /> },
      { path: "licensing/licenses/:id", element: <LicenseDetailPage /> },
      {
        path: "licensing/requirements",
        element: <RequirementAssessmentPage />,
      },
      {
        path: "licensing/requirements/:id",
        element: <RequirementResultPage />,
      },
      { path: "licensing/calendar", element: <ComplianceCalendarPage /> },
      { path: "licensing/cases", element: <ComplianceCasesPage /> },
      { path: "licensing/cases/:id", element: <ComplianceCasePage /> },
      { path: "licensing/information", element: <InformationRegistryPage /> },
      { path: "licensing/packets", element: <PacketBuilderPage /> },
      { path: "licensing/forms", element: <FormPreparationPage /> },
      { path: "portals", element: <PortalRegistryPage /> },
      { path: "portals/:id", element: <PortalDefinitionPage /> },
      { path: "portal-runs", element: <PortalRunQueuePage /> },
      { path: "portal-runs/:id", element: <PortalRunPage /> },
      {
        path: "portal-handoffs/:id",
        element: <PortalHandoffPage />,
      },
      {
        path: "pre-submission-snapshots/:id",
        element: (
          <RoleGuard role="Licensing.Reviewer">
            <PreSubmissionReviewPage />
          </RoleGuard>
        ),
      },
      {
        path: "portal-runs/:id/submission-evidence",
        element: <SubmissionEvidencePage />,
      },
      {
        path: "licensing/sources",
        element: (
          <RoleGuard role="Licensing.Manager">
            <RequirementSourcesPage />
          </RoleGuard>
        ),
      },
      {
        path: "licensing/import",
        element: (
          <RoleGuard role="Licensing.Admin">
            <MasterTrackerImportPage />
          </RoleGuard>
        ),
      },
      {
        path: "licensing/data-quality",
        element: (
          <RoleGuard role="Licensing.Manager">
            <DataQualityPage />
          </RoleGuard>
        ),
      },
      { path: "admin/rules", element: <AdminRulesPage /> },
      { path: "evaluation", element: <EvaluationPage /> },
      { path: "unauthorized", element: <UnauthorizedPage /> },
    ],
  },
]);
