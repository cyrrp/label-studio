import React from "react";
import { registerInterface, INTERFACE_API_VERSION } from "./registry";
import "./ReactCode";
import "./custom.css";

// External bundles share the host React instance, including hooks.
window.LabelStudioInterfaces = Object.freeze({ apiVersion: INTERFACE_API_VERSION, React, registerInterface });
export { registerInterface, INTERFACE_API_VERSION } from "./registry";
