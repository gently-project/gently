# Planning Context Hierarchy

This note maps the smart-microscopy context hierarchy into Gently plan mode.
It responds to the PR #23 discussion about making the planning layer the
biologist's primary way to interact with a DiSPIM, an organism, and later other
experimental modalities.

## Source Framework

Kesavan and Nordenfelt describe smart microscopy as a shift from passive data
collection toward active scientific collaboration. Their framework highlights
hierarchical context integration across four levels: technical, experimental,
theoretical, and conceptual context.

Reference:
P. S. Kesavan and P. Nordenfelt, "From observation to understanding: A
multi-agent framework for smart microscopy," Journal of Microscopy, 2026,
doi: 10.1111/jmi.70063.

Preprint:
https://arxiv.org/abs/2505.20466

## Gently Plan Item Mapping

Every important plan item can now carry `plan_context` alongside its executable
or measurable `spec`.

`technical`
: Instrument, sample, calibration, dataflow, and safety state. For the DiSPIM
  embryo workflow this includes bottom-overview XY finding, F/head-axis
  alignment, stage Z/head approach, `calibration_tools.py`, galvo-piezo
  calibration, detector state, and timelapse settings.

`experimental`
: Operator workflow, sample prep, controls, and user constraints. For the
  immediate Ryan/Brie workflow this means locate embryos, align the F/head axis,
  confirm calibration per embryo coordinate, then decide on timelapse.

`theoretical`
: The biological model, developmental process, mechanism, or measurement
  hypothesis that gives the image data meaning.

`conceptual`
: The higher-level scientific or human-instrument objective. This is the layer
  where the biologist should be able to say what they are trying to understand
  without first phrasing it as device commands.

Additional fields:
- `sample_entity`: the organism, embryo, tissue, region, or other entity being
  acted on or observed.
- `operator_context`: who is operating, calibrating, approving, or using the
  plan and what they need from the system.
- `constraints`: safety, timing, phototoxicity, calibration, or workflow
  constraints that must stay visible during planning.
- `success_question`: the question that should be answerable if the item works.

## Example

```json
{
  "technical": "Embryos found in XY with the bottom overview camera; F/head axis aligned; calibration confirmed before timelapse.",
  "experimental": "Ryan or Brie prepares poly-lysine-mounted C. elegans embryos, checks focus approach, and approves the first timelapse.",
  "theoretical": "Embryo developmental timing and morphology should remain interpretable across the planned imaging window.",
  "conceptual": "Let the biologist plan at the embryo-development level while Gently keeps the DiSPIM operations explicit.",
  "sample_entity": "C. elegans embryos on a poly-lysine-coated glass slide",
  "operator_context": "Ryan/Brie immediate DiSPIM users; Gently may automate calibration steps only after safety assumptions are explicit.",
  "constraints": [
    "Confirm calibration for each embryo coordinate before timelapse",
    "State F-drive/head-axis focus-finding assumptions before lowering toward sample focus",
    "Avoid overtravel beyond embryo focus toward the glass slide"
  ],
  "success_question": "Can the plan acquire reliable embryo timelapse data without hiding calibration or focus-safety assumptions?"
}
```

## Validation Behavior

Plan validation now warns, without blocking execution, when imaging items do not
carry the four context layers. It also warns when a DiSPIM embryo timelapse plan
does not state calibration and F-drive/head-axis focus-safety assumptions in the
technical context or constraints.

The warnings are deliberate: they keep the existing planning system usable while
making the missing planning structure visible for iteration.
