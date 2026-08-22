"""Project scaffolding templates.

All templates produce clean, typed, tested starter code following
SOLID/DRY conventions. Generated projects are immediately runnable
after installing dependencies.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# FastAPI backend
# ---------------------------------------------------------------------------

FASTAPI_FILES: dict[str, str] = {
    "pyproject.toml": """[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "sqlmodel>=0.0.16",
    "alembic>=1.13",
    "pydantic-settings>=2.2",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8", "httpx>=0.27"]

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
    "app/__init__.py": '"""{name} application package."""\n',
    "app/config.py": '''"""Environment-based configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "{name}"
    debug: bool = False
    database_url: str = "sqlite:///./{name}.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
''',
    "app/database.py": '''"""Database engine and session management."""

from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, echo=settings.debug)


def create_all() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
''',
    "app/models.py": '''"""SQLModel table models."""

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class Item(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(index=True, min_length=1, max_length=200)
    description: str = ""
    done: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
''',
    "app/schemas.py": '''"""Pydantic request/response schemas."""

from pydantic import BaseModel, Field


class ItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""


class ItemUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    done: bool | None = None


class ItemRead(BaseModel):
    id: int
    title: str
    description: str
    done: bool
''',
    "app/routers/__init__.py": '"""API routers."""\n',
    "app/routers/items.py": '''"""/items REST endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.database import get_session
from app.models import Item
from app.schemas import ItemCreate, ItemRead, ItemUpdate

router = APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=list[ItemRead])
async def list_items(session: Session = Depends(get_session)) -> list[Item]:
    return list(session.exec(select(Item).offset(0).limit(100)).all())


@router.post("", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
async def create_item(payload: ItemCreate, session: Session = Depends(get_session)) -> Item:
    item = Item(**payload.model_dump())
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.get("/{{item_id}}", response_model=ItemRead)
async def get_item(item_id: int, session: Session = Depends(get_session)) -> Item:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.patch("/{{item_id}}", response_model=ItemRead)
async def update_item(
    item_id: int, payload: ItemUpdate, session: Session = Depends(get_session)
) -> Item:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.delete("/{{item_id}}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: int, session: Session = Depends(get_session)) -> None:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    session.delete(item)
    session.commit()
''',
    "app/main.py": '''"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import create_all
from app.routers import items

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    create_all()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(items.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {{"status": "ok"}}
''',
    "tests/test_main.py": '''"""Smoke tests for the API."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {{"status": "ok"}}


def test_item_crud_roundtrip() -> None:
    created = client.post("/items", json={{"title": "first"}})
    assert created.status_code == 201
    item_id = created.json()["id"]

    fetched = client.get(f"/items/{{item_id}}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "first"

    deleted = client.delete(f"/items/{{item_id}}")
    assert deleted.status_code == 204
''',
    ".env.example": "DEBUG=true\nDATABASE_URL=sqlite:///./{name}.db\n",
    "README.md": '# {name}\n\nFastAPI backend generated by Kora.\n\n```bash\npip install -e ".[dev]"\nuvicorn app.main:app --reload\npytest\n```\n',
}

# ---------------------------------------------------------------------------
# React (Vite + TypeScript + Tailwind)
# ---------------------------------------------------------------------------

REACT_FILES: dict[str, str] = {
    "package.json": """{{
  "name": "{name}",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {{
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  }},
  "dependencies": {{
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  }},
  "devDependencies": {{
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.19",
    "postcss": "^8.4.39",
    "tailwindcss": "^3.4.6",
    "typescript": "^5.5.3",
    "vite": "^5.3.4",
    "vitest": "^2.0.3"
  }}
}}
""",
    "vite.config.ts": """import {{ defineConfig }} from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({{
  plugins: [react()],
  server: {{ port: 5173 }},
}});
""",
    "tsconfig.json": """{{
  "compilerOptions": {{
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noEmit": true,
    "skipLibCheck": true
  }},
  "include": ["src"]
}}
""",
    "tailwind.config.ts": """import type {{ Config }} from "tailwindcss";

export default {{
  content: ["./index.html", "./src/**/*.{{ts,tsx}}"],
  theme: {{ extend: {{}} }},
  plugins: [],
}} satisfies Config;
""",
    "postcss.config.js": """export default {{
  plugins: {{
    tailwindcss: {{}},
    autoprefixer: {{}},
  }},
}};
""",
    "index.html": """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{name}</title>
  </head>
  <body class="bg-slate-900 text-slate-100">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
""",
    "src/index.css": """@tailwind base;
@tailwind components;
@tailwind utilities;
""",
    "src/main.tsx": """import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
""",
    "src/App.tsx": """import {{ useState }} from "react";
import Button from "./components/Button";

export default function App(): JSX.Element {{
  const [count, setCount] = useState(0);

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-center justify-center gap-6">
      <h1 className="text-3xl font-bold">{name}</h1>
      <p className="text-slate-400">Vite + React + TypeScript + Tailwind</p>
      <Button onClick={{() => setCount((c) => c + 1)}}>count is {{count}}</Button>
    </main>
  );
}}
""",
    "src/components/Button.tsx": """type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement>;

export default function Button({{
  className = "",
  children,
  ...rest
}}: ButtonProps): JSX.Element {{
  const classes = [
    "rounded-lg bg-indigo-500 px-4 py-2 font-medium text-white",
    "transition hover:bg-indigo-400 disabled:opacity-50",
    className,
  ]
    .join(" ")
    .trim();

  return (
    <button className={{classes}} {{...rest}}>
      {{children}}
    </button>
  );
}}
""",
    "src/api/client.ts": """/** Minimal typed fetch wrapper for talking to a backend API. */

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {{
  constructor(public status: number, message: string) {{
    super(message);
    this.name = "ApiError";
  }}
}}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {{
  const response = await fetch(`${{BASE_URL}}${{path}}`, {{
    headers: {{ "Content-Type": "application/json" }},
    ...init,
  }});
  if (!response.ok) {{
    throw new ApiError(response.status, `API error ${{response.status}}: ${{await response.text()}}`);
  }}
  return (await response.json()) as T;
}}

export interface Item {{
  id: number;
  title: string;
  description: string;
  done: boolean;
}}

export const listItems = (): Promise<Item[]> => api<Item[]>("/items");

export const createItem = (title: string): Promise<Item> =>
  api<Item>("/items", {{ method: "POST", body: JSON.stringify({{ title }}) }});
""",
    "README.md": "# {name}\n\nReact web app generated by Kora.\n\n```bash\nnpm install\nnpm run dev\n```\n",
}

# ---------------------------------------------------------------------------
# Next.js (App Router + TS + Tailwind)
# ---------------------------------------------------------------------------

NEXTJS_FILES: dict[str, str] = {
    "package.json": """{{
  "name": "{name}",
  "private": true,
  "scripts": {{
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint"
  }},
  "dependencies": {{
    "next": "^14.2.5",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  }},
  "devDependencies": {{
    "@types/node": "^20.14.11",
    "@types/react": "^18.3.3",
    "autoprefixer": "^10.4.19",
    "postcss": "^8.4.39",
    "tailwindcss": "^3.4.6",
    "typescript": "^5.5.3"
  }}
}}
""",
    "next.config.mjs": "/** @type {{import('next').NextConfig}} */\nconst nextConfig = {{}};\n\nexport default nextConfig;\n",
    "tsconfig.json": """{{
  "compilerOptions": {{
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{{ "name": "next" }}],
    "paths": {{ "@/*": ["./src/*"] }}
  }},
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"],
  "exclude": ["node_modules"]
}}
""",
    "tailwind.config.ts": """import type {{ Config }} from "tailwindcss";

const config: Config = {{
  content: ["./src/**/*.{{ts,tsx}}"],
  theme: {{ extend: {{}} }},
  plugins: [],
}};
export default config;
""",
    "postcss.config.js": """module.exports = {{
  plugins: {{
    tailwindcss: {{}},
    autoprefixer: {{}},
  }},
}};
""",
    "src/app/globals.css": "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n",
    "src/app/layout.tsx": """import type {{ Metadata }} from "next";
import "./globals.css";

export const metadata: Metadata = {{
  title: "{name}",
  description: "Generated by Kora",
}};

export default function RootLayout({{
  children,
}}: Readonly<{{ children: React.ReactNode }}>) {{
  return (
    <html lang="en">
      <body className="min-h-screen bg-white text-slate-900 antialiased">{{children}}</body>
    </html>
  );
}}
""",
    "src/app/page.tsx": """export default function HomePage() {{
  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="text-2xl font-bold">{name}</h1>
      <p className="mt-2 text-slate-600">Next.js App Router project generated by Kora.</p>
    </main>
  );
}}
""",
    "README.md": "# {name}\n\nNext.js app generated by Kora.\n\n```bash\nnpm install\nnpm run dev\n```\n",
}

# ---------------------------------------------------------------------------
# Expo / React Native
# ---------------------------------------------------------------------------

EXPO_FILES: dict[str, str] = {
    "package.json": """{{
  "name": "{name}",
  "version": "0.1.0",
  "main": "expo/AppEntry.js",
  "scripts": {{
    "start": "expo start",
    "android": "expo start --android",
    "ios": "expo start --ios",
    "web": "expo start --web"
  }},
  "dependencies": {{
    "@react-navigation/native": "^6.1.17",
    "@react-navigation/native-stack": "^6.9.26",
    "expo": "~51.0.0",
    "react": "18.2.0",
    "react-native": "0.74.5",
    "react-native-safe-area-context": "4.10.5",
    "react-native-screens": "3.31.1"
  }},
  "devDependencies": {{
    "@types/react": "~18.2.79",
    "typescript": "~5.3.3"
  }}
}}
""",
    "app.json": """{{
  "expo": {{
    "name": "{name}",
    "slug": "{name}",
    "version": "0.1.0",
    "orientation": "portrait",
    "userInterfaceStyle": "automatic"
  }}
}}
""",
    "tsconfig.json": """{{
  "extends": "expo/tsconfig.base",
  "compilerOptions": {{
    "strict": true
  }},
  "include": ["**/*.ts", "**/*.tsx"]
}}
""",
    "App.tsx": """import Navigation from "./src/navigation";
import {{ StatusBar }} from "expo-status-bar";

export default function App() {{
  return (
    <>
      <Navigation />
      <StatusBar style="auto" />
    </>
  );
}}
""",
    "src/theme.ts": """export const colors = {{
  primary: "#6366f1",
  background: "#f8fafc",
  text: "#0f172a",
  muted: "#64748b",
}};

export const spacing = (units: number): number => units * 8;
""",
    "src/api/client.ts": """/** Typed API client for the mobile app. */

const BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Item {{
  id: number;
  title: string;
  description: string;
  done: boolean;
}}

export async function fetchItems(): Promise<Item[]> {{
  const response = await fetch(`${{BASE_URL}}/items`);
  if (!response.ok) throw new Error(`API error ${{response.status}}`);
  return (await response.json()) as Item[];
}}
""",
    "src/navigation/index.tsx": """import {{ NavigationContainer }} from "@react-navigation/native";
import {{ createNativeStackNavigator }} from "@react-navigation/native-stack";

import HomeScreen from "../screens/HomeScreen";
import DetailScreen from "../screens/DetailScreen";

export type RootStackParamList = {{
  Home: undefined;
  Detail: {{ itemId: number }};
}};

const Stack = createNativeStackNavigator<RootStackParamList>();

export default function Navigation() {{
  return (
    <NavigationContainer>
      <Stack.Navigator initialRouteName="Home">
        <Stack.Screen name="Home" component={{HomeScreen}} />
        <Stack.Screen name="Detail" component={{DetailScreen}} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}}
""",
    "src/screens/HomeScreen.tsx": """import {{ useEffect, useState }} from "react";
import {{ ActivityIndicator, FlatList, Text, View }} from "react-native";

import {{ fetchItems, type Item }} from "../api/client";
import {{ colors, spacing }} from "../theme";

export default function HomeScreen(): JSX.Element {{
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {{
    fetchItems()
      .then(setItems)
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }}, []);

  if (loading) return <ActivityIndicator style={{{{ marginTop: spacing(10) }}}} />;

  return (
    <FlatList
      contentContainerStyle={{{{ padding: spacing(2) }}}}
      data={{items}}
      keyExtractor={{(item) => String(item.id)}}
      renderItem={{({{ item }}) => (
        <View style={{{{ paddingVertical: spacing(1) }}}}>
          <Text style={{{{ color: colors.text, fontSize: 16 }}}}>{{item.title}}</Text>
        </View>
      )}}
      ListEmptyComponent={{<Text>No items yet.</Text>}}
    />
  );
}}
""",
    "src/screens/DetailScreen.tsx": """import {{ Text, View }} from "react-native";

import type {{ NativeStackScreenProps }} from "@react-navigation/native-stack";
import type {{ RootStackParamList }} from "../navigation";
import {{ spacing }} from "../theme";

type Props = NativeStackScreenProps<RootStackParamList, "Detail">;

export default function DetailScreen({{ route }}: Props): JSX.Element {{
  return (
    <View style={{{{ padding: spacing(2) }}}}>
      <Text>Item #{{route.params.itemId}}</Text>
    </View>
  );
}}
""",
    "README.md": "# {name}\n\nExpo React Native app generated by Kora.\n\n```bash\nnpm install\nnpx expo start\n```\n",
}

# ---------------------------------------------------------------------------
# Flutter (minimal - prefer `flutter create` when available)
# ---------------------------------------------------------------------------

FLUTTER_FILES: dict[str, str] = {
    "pubspec.yaml": """name: {snake_name}
description: Flutter app generated by Kora.
publish_to: "none"
version: 0.1.0+1

environment:
  sdk: ">=3.4.0 <4.0.0"

dependencies:
  flutter:
    sdk: flutter
  http: ^1.2.0

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^4.0.0

flutter:
  uses-material-design: true
""",
    "analysis_options.yaml": "include: package:flutter_lints/flutter.yaml\n",
    "lib/main.dart": """import 'package:flutter/material.dart';

void main() => runApp(const KoraApp());

class KoraApp extends StatelessWidget {{
  const KoraApp({{super.key}});

  @override
  Widget build(BuildContext context) {{
    return MaterialApp(
      title: '{title}',
      theme: ThemeData(colorSchemeSeed: Colors.indigo, useMaterial3: true),
      home: const HomePage(),
    );
  }}
}}

class HomePage extends StatelessWidget {{
  const HomePage({{super.key}});

  @override
  Widget build(BuildContext context) {{
    return Scaffold(
      appBar: AppBar(title: const Text('{title}')),
      body: const Center(child: Text('Generated by Kora')),
    );
  }}
}}
""",
    "test/widget_test.dart": """import 'package:flutter_test/flutter_test.dart';
import 'package:{snake_name}/main.dart';

void main() {{
  testWidgets('renders home page', (tester) async {{
    await tester.pumpWidget(const KoraApp());
    expect(find.text('{title}'), findsOneWidget);
  }});
}}
""",
}


def scaffold_files(project_type: str, name: str) -> dict[str, str]:
    """Return {relative_path: content} for the given project type."""
    templates: dict[str, dict[str, str]] = {
        "fastapi": FASTAPI_FILES,
        "react": REACT_FILES,
        "nextjs": NEXTJS_FILES,
        "expo": EXPO_FILES,
        "flutter": FLUTTER_FILES,
    }
    key = project_type.lower().replace("-", "").replace("_", "").replace(" ", "")
    alias = {
        "fastapi": "fastapi",
        "fastapiapp": "fastapi",
        "backend": "fastapi",
        "react": "react",
        "vite": "react",
        "reactvite": "react",
        "nextjs": "nextjs",
        "next": "nextjs",
        "expo": "expo",
        "reactnative": "expo",
        "mobile": "expo",
        "flutter": "flutter",
    }
    target = alias.get(key)
    if target is None or target not in templates:
        raise ValueError(
            f"Unknown project_type '{project_type}'. "
            f"Supported: fastapi, react (vite+ts+tailwind), nextjs, expo, flutter"
        )
    chosen = templates[target]
    snake = name.lower().replace("-", "_").replace(" ", "_")
    out: dict[str, str] = {}
    for rel, template in chosen.items():
        out[rel] = template.format(
            name=name, snake_name=snake, title=name.replace("-", " ").title()
        )
    return out


PROJECT_TYPE_DETECTORS: dict[str, tuple[str, ...]] = {
    "python-fastapi": ("pyproject.toml",),
    "react-vite": ("vite.config.ts",),
    "nextjs": ("next.config.mjs", "next.config.js"),
    "expo": ("app.json", "app.config.js"),
    "flutter": ("pubspec.yaml",),
    "node": ("package.json",),
}
