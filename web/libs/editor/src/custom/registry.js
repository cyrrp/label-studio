import { observable } from "mobx";

export const INTERFACE_API_VERSION = 1;
const interfaces = observable.map({}, { deep: false });
const loading = new Map();

export function registerInterface(name, definition) {
  if (!/^[a-z][a-z0-9-]*$/.test(name)) throw new Error(`Invalid interface name: ${name}`);
  if (definition?.apiVersion !== INTERFACE_API_VERSION) throw new Error(`Unsupported interface API: ${name}`);
  const component = definition.Component;
  if (
    typeof component !== "function" &&
    ![Symbol.for("react.memo"), Symbol.for("react.forward_ref")].includes(component?.$$typeof)
  ) {
    throw new Error(`Interface ${name} must provide a Component`);
  }
  if (interfaces.has(name)) throw new Error(`Interface already registered: ${name}`);
  interfaces.set(name, Object.freeze({ ...definition }));
}

export function getInterface(name) {
  return interfaces.get(name);
}

// Trusted classic scripts register through window.LabelStudioInterfaces.
// URLs are administrator-owned settings, never executable code from label XML.
export function loadInterface(name) {
  if (interfaces.has(name)) return Promise.resolve(interfaces.get(name));
  if (loading.has(name)) return loading.get(name);
  const modules = window.APP_SETTINGS?.custom_interface_modules ?? {};
  if (!Object.hasOwn(modules, name)) return Promise.reject(new Error(`Unknown interface: ${name}`));
  const promise = new Promise((resolve, reject) => {
    const url = new URL(modules[name], window.location.href);
    if (url.origin !== window.location.origin || !["http:", "https:"].includes(url.protocol)) {
      reject(new Error(`Interface module must use a same-origin URL: ${name}`));
      return;
    }
    const script = document.createElement("script");
    script.src = url.href;
    script.async = true;
    const finish = (error) => {
      clearTimeout(timer);
      script.onload = script.onerror = null;
      if (error) {
        script.remove();
        reject(error);
      } else resolve(interfaces.get(name));
    };
    const timer = setTimeout(() => finish(new Error(`Interface load timed out: ${name}`)), 30000);
    script.onload = () => finish(interfaces.has(name) ? null : new Error(`Module did not register interface: ${name}`));
    script.onerror = () => finish(new Error(`Unable to load interface: ${name}`));
    document.head.appendChild(script);
  });
  loading.set(name, promise);
  return promise;
}
