import { HtxWizard } from "./Wizard";

/**
 * Component registry for the CustomInterface dispatcher.
 * `<CustomInterface component="wizard" .../>` → `HtxWizard`.
 * Add new fork components here — each entry is a React component
 * receiving `{ item }` (the tag model, with `item.annotation` access).
 */
export const CUSTOM_COMPONENTS = {
  wizard: HtxWizard,
};
