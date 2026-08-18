// featureEdit.js
// Structured-editing fallback (Phase 2 item 4): which feature parameters
// can be edited directly as a number field, and how to patch a new value
// back into the json_ir. Deliberately scoped to simple scalar params on
// the feature types where "change this one number" is unambiguous --
// Loft/Sweep/Mirror stay read-only in this version (their parameters are
// structural -- source lists, planes -- not a single dimension a form
// field can represent cleanly). Sketch is editable only for the common
// single-primitive Rectangle/Circle case (a base block/cylinder footprint),
// not arbitrary multi-primitive sketches.
//
// Each field descriptor: { path: [...keys/indices into the feature
// object], label, value, step, min }. `path` is walked by applyFieldEdit
// to know where to write the new value -- e.g. a Sketch's rectangle width
// lives at ["primitives", 0, "parameters", "width"], not a top-level key.

export function getEditableFields(feature) {
  switch (feature.feature_type) {
    case "Extrude":
      return [{ path: ["amount"], label: "amount (mm)", value: feature.amount, step: 0.1 }];

    case "Revolve":
      return [{ path: ["angle"], label: "angle (deg)", value: feature.angle ?? 360, step: 1, min: 1, max: 360 }];

    case "Fillet":
      return [{ path: ["radius"], label: "radius (mm)", value: feature.radius, step: 0.1, min: 0.01 }];

    case "Chamfer":
      return [{ path: ["length"], label: "length (mm)", value: feature.length, step: 0.1, min: 0.01 }];

    case "Shell":
      return [{ path: ["thickness"], label: "thickness (mm)", value: feature.thickness, step: 0.1, min: 0.01 }];

    case "Hole":
      return [
        { path: ["radius"], label: "radius (mm)", value: feature.radius, step: 0.1, min: 0.01 },
        { path: ["depth"], label: "depth (mm)", value: feature.depth, step: 0.1, min: 0.01 },
      ];

    case "LinearPattern":
      return [
        { path: ["count"], label: "count", value: feature.count, step: 1, min: 1, max: 50 },
        { path: ["spacing"], label: "spacing (mm)", value: feature.spacing, step: 0.1 },
      ];

    case "CircularPattern":
      return [
        { path: ["count"], label: "count", value: feature.count, step: 1, min: 1, max: 50 },
        { path: ["angle"], label: "angle (deg)", value: feature.angle ?? 360, step: 1, min: 1, max: 3600 },
      ];

    case "Sketch": {
      if (!feature.primitives || feature.primitives.length !== 1) return null;
      const prim = feature.primitives[0];
      if (prim.type === "Rectangle") {
        return [
          { path: ["primitives", 0, "parameters", "width"], label: "width (mm)", value: prim.parameters.width, step: 0.1 },
          { path: ["primitives", 0, "parameters", "height"], label: "height (mm)", value: prim.parameters.height, step: 0.1 },
        ];
      }
      if (prim.type === "Circle") {
        return [
          { path: ["primitives", 0, "parameters", "radius"], label: "radius (mm)", value: prim.parameters.radius, step: 0.1, min: 0.01 },
        ];
      }
      return null; // Polygon/Slot/wire primitives -- not editable in v1
    }

    default:
      return null; // Loft, Sweep, Mirror -- structural params, not a form field
  }
}

/** Deep-clones jsonIr and writes `value` at `path` within the feature
 * matching `featureId`. Never mutates the input. */
export function applyFieldEdit(jsonIr, featureId, path, value) {
  const next = structuredClone(jsonIr);
  const feature = next.features.find((f) => f.id === featureId);
  if (!feature) {
    throw new Error(`applyFieldEdit: no feature with id '${featureId}'`);
  }
  let node = feature;
  for (let i = 0; i < path.length - 1; i++) {
    node = node[path[i]];
    if (node == null) {
      throw new Error(`applyFieldEdit: path ${JSON.stringify(path)} does not exist on feature '${featureId}'`);
    }
  }
  node[path[path.length - 1]] = value;
  return next;
}
