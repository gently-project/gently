// Names one UI script reads from another. The scripts under gently/ui/web/static/js
// are classic <script>s sharing one global scope; TypeScript cannot see a global that
// is hung on window, or one whose file also has module.exports, so they are declared
// here. undefined-names.test.mjs fails on any name that is in neither place.
declare const AcquisitionPlan: any;
declare const BrightfieldRefs: any;
declare const CalibrationArchive: any;
declare const CalProgressPanel: any;
declare const CameraPanel: any;
declare const CampaignsApp: any;
declare const createOverviewStage: any;
declare const FieldsPanel: any;
declare const GentlyTime: any;
declare const HardwareTimeline: any;
declare const HardwareTimelineMath: any;
declare const ImageView: any;
declare const LightPanel: any;
declare const MarkingPanel: any;
declare const NumRow: any;
declare const openCampaign: any;
declare const OperateMath: any;
declare const OverviewStage: any;
declare const RegionEditor: any;
declare const RosterPanel: any;
declare const RunPreflight: any;
declare const RunView: any;
declare const SettingsStore: any;
declare const showToast: any;
declare const stageColor: any;
declare const stageKey: any;
declare const StagePad: any;
declare const THREE: any;
declare const U16Math: any;
declare const XYLimitsState: any;
