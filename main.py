import os

import discord
import requests
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

def merge_intervals(intervals):
  intervals = [tuple(interval.split(' - ')) for interval in intervals]
  
  intervals.sort(key=lambda x: x[0])
  
  merged_intervals = []
  current_start, current_end = intervals[0]

  for start, end in intervals[1:]:
    if start <= current_end:
      current_end = max(current_end, end)
    else:
      merged_intervals.append((current_start, current_end))
      current_start, current_end = start, end

  merged_intervals.append((current_start, current_end))

  merged_time_intervals = [
    f"{start} - {end}"
    for start, end in merged_intervals
  ]

  return merged_time_intervals

def check_jadwal(place, date):
  empty_slots = set()
  vanue_code = {
      "kukusan": 307,
      "sima": 726
  }
  payload = {"venue_id": vanue_code[place.lower()], "date": date}

  response = requests.get(
      f"https://ayo.co.id/venues-ajax/op-times-and-fields",
      params=payload).json()

  if not len(response["op_time"]["hours"]):
    return f"Maaf, jadwal untuk {response['op_time']['day']}, {date} belum dibuka"

  for field in response["fields"]:
    for slot in field["slots"]:
      if slot["is_available"]:
        empty_slots.add(f"{slot['start_time']} - {slot['end_time']}")

  if not (len(empty_slots)):
    return f"Maaf, jadwal untuk {response['op_time']['day']}, {date} sudah penuh"

  empty_slots = list(empty_slots)
  empty_slots.sort()
  merges_slots = merge_intervals(empty_slots)
  joined_slots = '\n'.join(merges_slots)
  text = f"""
Berikut jadwal GOR {place.capitalize()} yang tersedia untuk Hari {response['op_time']['day']}, Tanggal {date}:

{joined_slots}
  """

  return text


@bot.event
async def on_ready():
  print(f"{bot.user} Started")
  try:
    synced = await bot.tree.sync()
    print(f"Synced {len(synced)} command(s)")
  except Exception as e:
    print(e)


@bot.event
async def on_message(message):
  if message.author == bot.user:
    return

  if message.content.startswith("!hello"):
    await message.channel.send("Hello!")


@bot.tree.command(name='jadwal')
@app_commands.describe(place='Nama GOR', date='YYYY-MM-DD')
async def jadwal(interaction, place: str, date: str):
  if not(place.lower() in ['kukusan', 'sima']):
    await interaction.response.send_message(
        "Maaf, baru bisa gor kukusan dan sima Kak 😭😭")
    return
  res = check_jadwal(place, date)
  await interaction.response.send_message(res)


bot.run(TOKEN)