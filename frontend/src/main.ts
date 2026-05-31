/**
 * Every-page entry (base.html). Pulls in the global stylesheet (Tailwind +
 * overflow guards) and the command palette. Issue #14 / Phase 1.
 * Issue #8 (Phase 6): the accessible mobile-nav drawer.
 */

import "./styles/app.css";
import "./cmdk";
import { initNav } from "./nav";

initNav();
