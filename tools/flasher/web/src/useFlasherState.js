import { useEffect, useState } from "react";
import { subscribeState } from "./flasherState.js";

/** The shared /api/state value. null until the first response arrives. */
export default function useFlasherState() {
  const [s, setS] = useState(null);
  useEffect(() => subscribeState(setS), []);
  return s;
}
