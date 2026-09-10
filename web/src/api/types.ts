/** Shapes returned by the `pcs` HTTP API (mirrors pcs.web_api.routes). */

export interface Project {
  id: string;
  name: string;
  root_path: string;
}

export interface Briefing {
  project: string;
  briefing: string;
}

export interface RegisterProjectInput {
  name: string;
  root_path: string;
  overview: string;
}

export interface Health {
  status: string;
  bind_mode: string;
  bind_host: string;
}
