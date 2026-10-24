/**
 * Request types generated from the FastAPI OpenAPI document (`npm run gen:api` reads
 * ../backend/openapi.json). The backend declares request bodies precisely and response bodies as
 * untyped dicts, so request types come from here and response types from the Zod schemas
 * (schemas.ts). CI regenerates and typechecks, so a renamed request field fails the build.
 */
import type { components } from './openapi.gen';

type S = components['schemas'];
export type ResolveIn = S['ResolveIn'];
export type DismissIn = S['DismissIn'];
export type ScenarioIn = S['ScenarioIn'];
export type PropertyPatch = S['PropertyPatch'];
export type SimulateIn = S['SimulateIn'];
