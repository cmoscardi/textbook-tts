## Here's what i am trying to do

1. Use the builtin `npx supabase start` to run local supabase dev environment
2. Make sure DB seeding works with this setup. in particular hte object creation policy stuff that isn't firing on migrate?
3. Convert the hitting of ml-service into a supabase edge function so that we don't expose the ml service url and can be lazy about security
   - make sure to use env vars for the hostname and other shit
   - set up some kind of token requirement for ml-service
4. clean up all the old supabase crap
