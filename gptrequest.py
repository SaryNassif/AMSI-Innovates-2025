from openai import OpenAI
import os
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

message_input = str(input("Enter Your Prompt:"))

completion = client.chat.completions.create(
  model="gpt-4o-mini",
  messages=[
    {"role": "user", "content": f"{message_input}"}
  ]
)

print(completion.choices[0].message.content)