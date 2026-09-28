// Every icon in the app comes through this file, and only this file
// imports from an icon pack. Swapping packs (or style) is a change here
// alone -- components import semantic names (Folder, Close, Play), never
// a pack-specific one (PiFolder).
//
// Pack: Phosphor, via react-icons' per-pack ESM entry. Measured before
// choosing: nine icons from react-icons/pi, /tb or /ri all cost the same
// (+5 modules, ~+1 kB gzipped over hand-inlined SVG), because per-pack
// imports tree-shake cleanly. That's the difference from lucide-react,
// whose barrel export dragged ~1900 modules into the build. Phosphor was
// picked over Tabler/Remix purely on looks: Tabler is close enough to
// lucide's style to read as the same thing.
//
// Never import from "react-icons" (the root) -- only a pack subpath.
export {
  PiCheck as Check,
  PiCaretDown as ChevronDown,
  PiCaretUp as ChevronUp,
  PiFolderSimple as Folder,
  PiFile as File,
  PiX as Close,
  PiPlay as Play,
  PiArrowUp as ArrowUp,
  PiArrowDown as ArrowDown,
  PiArrowUUpLeft as ParentFolder,
  PiFunction as FunctionIcon,
  PiPlus as Plus,
  PiTrash as Trash,
  PiMagnifyingGlass as Search,
} from "react-icons/pi";
