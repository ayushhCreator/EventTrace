-- Supabase-specific setup: RLS policies + auth trigger
-- Run this once in the Supabase SQL editor AFTER running ensure_schema()
-- (which creates the profiles and tracked_cases tables)

-- ── Enable RLS ────────────────────────────────────────────────────────────────

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE tracked_cases ENABLE ROW LEVEL SECURITY;

-- ── Profiles ─────────────────────────────────────────────────────────────────

-- Users can only read/update their own profile
CREATE POLICY "own profile read"
  ON profiles FOR SELECT
  USING (id = auth.uid()::text);

CREATE POLICY "own profile update"
  ON profiles FOR UPDATE
  USING (id = auth.uid()::text);

-- ── Tracked cases ─────────────────────────────────────────────────────────────

CREATE POLICY "own tracked cases"
  ON tracked_cases FOR ALL
  USING (user_id = auth.uid()::text);

-- ── Auto-create profile on signup ─────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.profiles(id, email, display_name, created_at)
  VALUES (
    NEW.id::text,
    NEW.email,
    COALESCE(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email, '@', 1)),
    NOW()::text
  )
  ON CONFLICT(id) DO NOTHING;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ── Allow public read on causelist/display data (no login needed) ─────────────

ALTER TABLE causelist_bench ENABLE ROW LEVEL SECURITY;
ALTER TABLE causelist_case ENABLE ROW LEVEL SECURITY;
ALTER TABLE current_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_trace ENABLE ROW LEVEL SECURITY;
ALTER TABLE vc_zoom_link ENABLE ROW LEVEL SECURITY;

-- Public read — no login required for court data
CREATE POLICY "public read causelist_bench"
  ON causelist_bench FOR SELECT USING (true);

CREATE POLICY "public read causelist_case"
  ON causelist_case FOR SELECT USING (true);

CREATE POLICY "public read current_state"
  ON current_state FOR SELECT USING (true);

CREATE POLICY "public read event_trace"
  ON event_trace FOR SELECT USING (true);

CREATE POLICY "public read vc_zoom_link"
  ON vc_zoom_link FOR SELECT USING (true);

-- Backend service role bypasses RLS (Railway API uses service_role key)
-- No extra policy needed — service_role always bypasses RLS in Supabase.
