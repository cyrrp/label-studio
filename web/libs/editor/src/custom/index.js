/**
 * Fork extensions entry point.
 *
 * Imported from `components/App/App.jsx` right after `../../tags/Custom`, so the
 * real `custominterface` registration below overwrites the OSS "Enterprise
 * only" placeholder model/view. `tags/Custom.jsx` itself stays untouched — its
 * `!Registry.models.custominterface` guard remains a safety net on merges.
 */
import Registry from "../core/Registry";
import { CustomInterfaceModel } from "./CustomInterface";
import "./custom.css";

// The stub also registered `custominterface` as an object type; keep that
// semantics (tag stays out of `toNames`/results) even if import order changes.
if (!Registry.objectTypes().some((m) => m.name === "CustomInterfaceModel")) {
  Registry.addObjectType(CustomInterfaceModel);
}
