import { registerInterface } from "../registry";
import { HtxWizard } from "./Wizard";
import { DocumentAssessment } from "./DocumentAssessment";

registerInterface("wizard", { apiVersion: 1, Component: HtxWizard });
registerInterface("document-assessment", { apiVersion: 1, Component: DocumentAssessment });
