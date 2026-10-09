import React, { useEffect, useMemo, useState } from "react";
import { observer } from "mobx-react";
import { isAlive, types } from "mobx-state-tree";
import Registry from "../core/Registry";
import { InterfaceModel } from "./InterfaceModel";
import { WizardInterfaceModel } from "./WizardModel";
import { getInterface, loadInterface } from "./registry";
import { createInterfaceAPI } from "./api";
import "./components";

const resolveModel = (snapshot) => (snapshot.component === "wizard" ? WizardInterfaceModel : InterfaceModel);

export const ReactCodeModel = types.union(
  {
    dispatcher: resolveModel,
  },
  WizardInterfaceModel,
  InterfaceModel,
);

// Config validation needs concrete model properties before an instance exists.
ReactCodeModel.getValidationModel = resolveModel;

class InterfaceErrorBoundary extends React.Component {
  state = { error: null };
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error) {
    this.props.item.setRuntimeError(error.message);
  }
  render() {
    return this.state.error ? (
      <div role="alert" className="lsx-custom--unknown">
        Interface error: {this.state.error.message}
      </div>
    ) : (
      this.props.children
    );
  }
}

const InterfaceContent = observer(({ item, definition }) => {
  const api = useMemo(() => createInterfaceAPI(item), [item, item.annotation]);
  useEffect(() => () => api.dispose(), [api]);
  // Track here so plain external React components receive fresh values.
  const values = Object.fromEntries(api.outputs.map((name) => [name, api.getValue(name)]));
  const config = api.config;
  const readOnly = api.readOnly;
  const task = api.task;
  const Comp = definition.Component;
  return (
    <Comp
      api={api}
      values={values}
      config={config}
      readOnly={readOnly}
      task={task}
      {...(item.isNavigation ? { item } : {})}
    />
  );
});

export const HtxReactCode = observer(({ item }) => {
  const definition = getInterface(item.component);
  const [error, setError] = useState(null);
  useEffect(() => {
    let active = true;
    loadInterface(item.component).catch((error) => {
      if (active && isAlive(item)) {
        item.setRuntimeError(error.message);
        setError(error.message);
      }
    });
    return () => {
      active = false;
    };
  }, [item]);
  if (error)
    return (
      <div role="alert" className="lsx-custom--unknown">
        {error}
      </div>
    );
  if (!definition) return <div role="status">Loading interface: {item.component}</div>;
  return (
    <InterfaceErrorBoundary key={`${item.id}:${item.annotation?.id}`} item={item}>
      <InterfaceContent item={item} definition={definition} />
    </InterfaceErrorBoundary>
  );
});

Registry.addTag("reactcode", ReactCodeModel, HtxReactCode);
for (const model of [InterfaceModel, WizardInterfaceModel]) {
  Registry.views_models[model.name] = HtxReactCode;
  if (!Registry.objectTypes().includes(model)) Registry.addObjectType(model);
}
