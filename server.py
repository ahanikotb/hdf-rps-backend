from fastapi import FastAPI
from fastapi_socketio import SocketManager
import uvicorn
from web3 import Web3
import json
from pymongo import MongoClient
from eth_account.messages import encode_defunct
import time
import jwt
from constants import SECURITYSEED, OPENSEAADDRESS, ROOMTIMEOUT, PRIVATE_KEY, ETH_PROVIDER, HTTP_PROVIDER, GAMEMONEYMANAGER, MONGODB_CLIENT, TOKENNAME
securitySeed = SECURITYSEED
app = FastAPI()

client = MongoClient(MONGODB_CLIENT)

# TODO ADD JWT TOKEN PROTECTION
# in this version we need to actually make a concept of tables so users would only pay the fees when unwraping if they got on a table if they get on a table
# we make user sign message that we translate here to make sure its him that send it
# sign tx first to sign in and we unpack it


def getUser(nftNo):
    user = client['HDF']['users'].find_one({"nftNo": nftNo})
    return user


def generateJWTTOKEN(socketId, nftNo):
    return jwt.encode({"socketId": socketId, "nftNo": nftNo}, securitySeed, algorithm="HS256")


def decodeToken(token):
    return jwt.decode(token, securitySeed, algorithms=["HS256"])


def getUserBySocketId(socketId):
    user = client['HDF']['users'].find_one({"socketId": socketId})
    return user


def validateDeposit(txHash, user, amountDeposited):
    w3 = Web3(Web3.HTTPProvider(HTTP_PROVIDER))
    f = open(
        '/Users/ahmedkotb/Documents/Coding/rockpapersissors/erc20abi.json', 'r')
    erc20abi = json.load(f)
    txReciept = w3.eth.get_transaction_receipt(txHash)
    gameTokenContract = w3.eth.contract(address=Web3.toChecksumAddress(
        GAMETOKEN), abi=erc20abi)
    parsedTxEvent = gameTokenContract.events.Transfer().processReceipt(txReciept)
    eventFrom = parsedTxEvent[0]['args']['from']
    eventTo = parsedTxEvent[0]['args']['to']
    eventValue = parsedTxEvent[0]['args']['value']
    if eventFrom.lower() == user['address'].lower() and eventTo.lower() == GAMEMONEYMANAGER.lower() and str(
            amountDeposited) == str(eventValue):
        return True
    return False


def validateBuy(txHash, user, amountDeposited):
    w3 = Web3(Web3.HTTPProvider(HTTP_PROVIDER))
    f = open(
        './TOKENCLAIMPROXY.json', 'r')
    erc20abi = json.load(f)
    txReciept = w3.eth.get_transaction_receipt(txHash)
    gameBrainContract = w3.eth.contract(address=Web3.toChecksumAddress(
        GAMEMONEYMANAGER), abi=erc20abi)
    parsedTxEvent = gameBrainContract.events.Deposit().processReceipt(txReciept)
    eventFrom = parsedTxEvent[0]['args']['from']
    eventValue = parsedTxEvent[0]['args']['value']
    if eventFrom.lower() == user['address'].lower() and str(
            amountDeposited) == str(eventValue):
        return True
    return False


async def updateWinner(socketId, nftNo, betsize):
    user = getUser(nftNo)
    # 20 percent goes to house
    quotient = 2 / 10
    houseAmount = int(betsize * quotient)
    user['balance'] += betsize - houseAmount
    # update house balance
    increasePendingEarnings(houseAmount)
    user['stats']['totalWins'] += 1
    user['stats']['totalBetted'] += betsize
    getUserDb().replace_one({"nftNo": nftNo}, user)
    userData = userFromRecord(user)
    await socket_manager.emit('userInfo', userData, to=socketId)


async def updateLoser(socketId, nftNo, betsize):
    user = getUser(nftNo)
    user['balance'] -= betsize
    user['stats']['totalBetted'] += betsize
    getUserDb().replace_one({"nftNo": nftNo}, user)
    userData = userFromRecord(user)
    try:
        await socket_manager.emit('userInfo', userData, to=socketId)
    except:
        pass


# TODO Implement a away for us to retrieve user tx if they want it


def getUserDb():
    return client['HDF']['users']


def getFinanceDb():
    return client['HDF']['finance']


def getStatsDb():
    return client['HDF']['stats']


def getGamesDb():
    return client['Games']


def resetGames():
    client['Games']['active'].drop()
    client['Games']['inactive'].drop()


def getActiveGames():
    return client['Games']['active']


def getInactiveGames():
    return client['Games']['inactive']


# FUNCTION THAT CHECKS IF USER IS ACTIVE AND HIS TOKEN IS THE CORRECT VALUE
def securityCheck(socketId, jwtToken):
    if jwtToken == '':
        return False
    user = getUserBySocketId(socketId)
    if user['active'] == True and user['accessToken'] != "" and user['accessToken'] == jwtToken:
        return True
    else:
        return False


def closeRoom(roomData, result, winnerNFTNO):
    roomData['status'] = "finished"
    roomData['result'] = result
    roomData['winner'] = winnerNFTNO
    getActiveGames().delete_one({"_id": roomData['nonce']})
    getInactiveGames().insert_one(roomData)


def closeThisRoom(roomData):
    # CHECK IF ITS STILL ACTIVE BEFORE DELETING IT
    if getActiveGames().find_one({"_id": roomData['_id']}) != None:
        # fast way of closing room without waiting
        getActiveGames().delete_one({"_id": roomData['_id']})
        getInactiveGames().insert_one(roomData)


def updateRoom(roomData, result):
    getActiveGames().replace_one({"_id": roomData['nonce']}, roomData)


# def initFinanceDb():
#     finanaceDB = getFinanceDb()
#     finanaceDB.insert_one({
#         "withdrawNonce": 0,
#         "HouseProfits": 0,  # money payed  2 % 0f totatl
#         "PAYEDTOUSERS": 0,  # moneypaid  98 of total
#         "UNPAID": 0,  # unpaid 100%
#     })


def initStatsDb():
    statsDb = getStatsDb()
    statsDb.replace_one({"_id": 0, }, {"_id": 0,
                                       "roomNonce": 0,
                                       "pendingEarnings": 0,
                                       "withdrawNonce": 0,
                                       "tvl": 0,
                                       }, upsert=True)


def incrementWithdrawNonce():
    stats = getStatsDb().find_one({"_id": 0})
    stats['withdrawNonce'] += 1
    getStatsDb().replace_one({"_id": 0}, stats)


def increasePendingEarnings(amount):
    stats = getStatsDb().find_one({"_id": 0})
    stats['pendingEarnings'] += amount
    getStatsDb().replace_one({"_id": 0}, stats)


def getPendingEarnings():
    stats = getStatsDb().find_one({"_id": 0})
    return stats['pendingEarnings']


def decreasePendingEarnings(amount):
    stats = getStatsDb().find_one({"_id": 0})
    stats['pendingEarnings'] -= amount
    getStatsDb().replace_one({"_id": 0}, stats)


def incrementRoomCount():
    stats = getStatsDb().find_one({"_id": 0})
    stats['roomNonce'] += 1
    getStatsDb().replace_one({"_id": 0}, stats)


def decrementRoomCount():
    stats = getStatsDb().find_one({"_id": 0})
    stats['roomNonce'] -= 1
    getStatsDb().replace_one({"_id": 0}, stats)


def getRoomCount():
    return getStatsDb().find_one({"_id": 0, })['roomNonce']


def tokenNoToId(tokenNo):
    f = open(
        '/Users/ahmedkotb/Documents/Coding/rockpapersissors/collectionData.json', 'r')
    data = json.load(f)
    return data[tokenNo]


async def increaseUserFunds(socketId, nftNo, txHash, amount):
    user = getUser(nftNo)
    user['deposits'].append(txHash)
    user['balance'] += (int(amount) / 10 ** 18)
    getUserDb().replace_one({"nftNo": nftNo}, user)
    userData = userFromRecord(user)
    await socket_manager.emit('userInfo', userData, to=socketId)


async def decreaseUserFunds(socketId, nftNo, amount, txnData):
    user = getUser(nftNo)
    user['withdrawals'].append(txnData)
    user['balance'] -= amount
    getUserDb().replace_one({"nftNo": nftNo}, user)
    userData = userFromRecord(user)
    await socket_manager.emit('userInfo', userData, to=socketId)


async def processUserDeposit(socketId, nftNo, txHash, amount, jwtToken):
    if securityCheck(socketId, jwtToken) != True:
        return None
    user = getUser(nftNo)
    if txHash not in user['deposits']:
        if validateDeposit(txHash, user, amount):
            await increaseUserFunds(socketId, nftNo, txHash, amount)


async def processUserBuy(socketId, nftNo, txHash, amount, jwtToken):
    if securityCheck(socketId, jwtToken) != True:
        return None
    user = getUser(nftNo)
    if txHash not in user['deposits']:
        if validateBuy(txHash, user, amount):
            await increaseUserFunds(socketId, nftNo, txHash, amount)


async def processUserWithdraw(socketId, nftNo, amount, jwtToken):
    if securityCheck(socketId, jwtToken) != True:
        return None
    # Sign tx and send it to user
    user = getUser(nftNo)
    if int(user['balance']) < int(amount) / 10 ** 18:
        await socket_manager.emit('Error', "You Don't Own Enough Tokens For That", to=socketId)
        return
        # get Withdraw Nonce
    withdrawNonce = getStatsDb().find_one({"_id": 0, })['withdrawNonce']
    pendingHouseEarnings = getPendingEarnings()
    wTxData = makeWithdrawTx(user['address'], amount, pendingHouseEarnings,
                             withdrawNonce, GAMEMONEYMANAGER)
    incrementWithdrawNonce()
    decreasePendingEarnings(pendingHouseEarnings)
    # decrease User FUNDS
    await socket_manager.emit('withdrawTxReady', wTxData, to=socketId)
    await decreaseUserFunds(socketId, nftNo, int(amount) / 10 ** 18, wTxData)


def doesOwnToken(address, tokenId):
    f = open(
        '/Users/ahmedkotb/Documents/Coding/rockpapersissors/erc1155abi.json', 'r')
    erc1155abi = json.load(f)
    w3 = Web3(Web3.HTTPProvider(ETH_PROVIDER))
    OPENSEAPROXY = Web3.toChecksumAddress(
        OPENSEAADDRESS)
    contract = w3.eth.contract(address=OPENSEAPROXY, abi=erc1155abi)
    result = contract.functions.balanceOf(
        Web3.toChecksumAddress(address), int(tokenId)).call()
    return result


def setAccountOnline(socketId):
    user = getUserBySocketId(socketId)
    user['active'] = True
    getUserDb().replace_one({"nftNo": user['nftNo']}, user)


def setAccountOffline(socketId):
    user = getUserBySocketId(socketId)
    user['active'] = False
    user['accessToken'] = ''
    getUserDb().replace_one({"nftNo": user['nftNo']}, user)


def isAccountOnline(socketId):
    user = getUserBySocketId(socketId)
    if user['active'] == True:
        return True
    else:
        return False

    # user = getUser(nftNo)
    # user['balance'] -= betsize
    # user['stats']['totalBetted'] += betsize
    # getUserDb().replace_one({"nftNo": nftNo}, user)
    # pass

# TODO INCLUDE SIGNED MESSAGE TO VERIFY TRANSACTIONS


def createAccount(accoundAddress, nftID, nftNo, signedMessage, socketId, jwtToken):
    userDB = getUserDb()
    userDB.insert_one(
        {'socketId': socketId,
         "active": True,
         "accessToken": jwtToken,
         "_id": nftNo,
         "nftNo": nftNo,
         "nftID": nftID,
         "address": accoundAddress,
         "balance": 10,
         "signedMessage": signedMessage,
         "totalUnpaid": 0,
         "deposits": [],
         "withdrawals": [],
         "stats": {
             "totalWins": 0,
             "totalBetted": 0
         }
         }
    )


socket_manager = SocketManager(
    app=app)
# app.mount("/static", StaticFiles(directory="static"), name="static")

playersConnected = 0
ROOMCOUNT = 0
ROOMMAPPING = {}
ROOMSTATUS = {}


# "ROOMID" INT => players,status,
# status = completed | waiting | playing
# used to protect tx from getting replayed on the smart contract's end


def reverseScore(score):
    result = ""
    for i in score:
        if i == "1":
            result = result + "0"
        else:
            result = result + "1"

    return result


def makeWithdrawTx(reciepientAddress, amount, pendingHouseEarnings, nonce, contractAddress):
    w3 = Web3(Web3.HTTPProvider(HTTP_PROVIDER))
    abiEncoded = w3.soliditySha3(["address", "uint256", "uint256", "uint256", "address"],
                                 [Web3.toChecksumAddress(reciepientAddress), int(amount),
                                  int(pendingHouseEarnings *
                                      10 ** 19), int(nonce),
                                  Web3.toChecksumAddress(contractAddress)])
    hash = abiEncoded.hex()
    message = encode_defunct(hexstr=hash)
    signed_message = w3.eth.account.sign_message(
        message, private_key=PRIVATE_KEY)
    return {
        "sig": signed_message.signature.hex(), "pendingHouseEarnings": int(pendingHouseEarnings * 10 ** 19),
        "nonce": nonce, "contractAddress": contractAddress, "amount": amount
    }


def calulateWinner(player1choice, player2choice):
    if player1choice["choice"] == "Rock" and player2choice["choice"] == "Paper":
        return player2choice["socketId"]
    if player1choice["choice"] == "Rock" and player2choice["choice"] == "Rock":
        return "draw"
    if player1choice["choice"] == "Rock" and player2choice["choice"] == "Scissors":
        return player1choice["socketId"]
    if player1choice["choice"] == "Paper" and player2choice["choice"] == "Paper":
        return "draw"
    if player1choice["choice"] == "Paper" and player2choice["choice"] == "Rock":
        return player1choice["socketId"]
    if player1choice["choice"] == "Paper" and player2choice["choice"] == "Scissors":
        return player2choice["socketId"]
    if player1choice["choice"] == "Scissors" and player2choice["choice"] == "Paper":
        return player1choice["socketId"]
    if player1choice["choice"] == "Scissors" and player2choice["choice"] == "Rock":
        return player2choice["socketId"]
    if player1choice["choice"] == "Scissors" and player2choice["choice"] == "Scissors":
        return "draw"
    if player1choice["choice"] == "notrevealed" and player2choice["choice"] == "notrevealed":
        return "house"
    if player1choice["choice"] == "notrevealed" and player2choice["choice"] == "Rock":
        return player2choice["socketId"]
    if player1choice["choice"] == "notrevealed" and player2choice["choice"] == "Paper":
        return player2choice["socketId"]
    if player1choice["choice"] == "notrevealed" and player2choice["choice"] == "Scissors":
        return player2choice["socketId"]
    if player1choice["choice"] == "Rock" and player2choice["choice"] == "notrevealed":
        return player1choice["socketId"]
    if player1choice["choice"] == "Paper" and player2choice["choice"] == "notrevealed":
        return player1choice["socketId"]
    if player1choice["choice"] == "Scissors" and player2choice["choice"] == "notrevealed":
        return player1choice["socketId"]


async def handleConnection(socketId, requestData, messages):
    pass


# update the room Manager to use db to get nonce for room count as well as continue


async def roomManager(socketId, nftNo, betSize):
    # TODO Implement a way for a user not to be able to online in two places at the same time as well to avoid conflict

    # global ROOMCOUNT
    # if ROOMCOUNT = 0:
    #     initStatsDb()
    #     ROOMCOUNT+1
    if getUser(nftNo).get('balance') < betSize:
        await socket_manager.emit('Error', 'You Need To Have A Minimum of 5 ' + TOKENNAME + ' Tokens To Play')
        # create an emit that handles this shit
        return

    # global ROOMMAPPING
    global playersConnected
    playersConnected += 1
    ROOMCOUNT = getRoomCount()
    if playersConnected % 2 != 0:
        # ROOMSTATUS[ROOMCOUNT] = {"nonce": ROOMCOUNT, "betSize": betSize,
        #                          "status": "waiting",
        #                          "players": 1,
        #                          "player1": {"socketId": sockedId, "nftNo": nftNo}
        #                          }
        getActiveGames().insert_one({"_id": ROOMCOUNT, "nonce": ROOMCOUNT, "betSize": betSize,
                                     "status": "waiting", "betRaised": False, "betRaiseAmount": 0,
                                     "betRaiseProposed": True, "rematchProposed": {"state": False, "initsocket": ""},
                                     "players": 1, "score": "",
                                     "player1": {"socketId": socketId, "nftNo": nftNo, "notResponding": False,
                                                 "timestamp": 0}
                                     })
        socket_manager.enter_room(socketId, (ROOMCOUNT))

        # room is created and room count is incremented room count is also the id for this room
        # ROOMCOUNT += 1
        incrementRoomCount()

        # add to db
    # check to make sure that the same user can't play against himself
    # elif playersConnected % 2 == 0 and userInRoom(nftNo) == False:
    elif playersConnected % 2 == 0:
        gameRoom = getActiveGames().find_one({"_id": ROOMCOUNT - 1})
        gameRoom["status"] = "playing"
        gameRoom["players"] = 2
        gameRoom["player2"] = {
            "socketId": socketId, "nftNo": nftNo, "notResponding": False, "timestamp": 0}
        getActiveGames().replace_one({"_id": ROOMCOUNT - 1}, gameRoom)
    # MAP USER TO ROOM
    # ROOMMAPPING[sockedId] = ROOMCOUNT-1
    # print(ROOMSTATUS[ROOMCOUNT-1])
    print('PLAYERS CONNECTED ' + str(playersConnected))
    print('ROOMS ' + str(ROOMCOUNT))
    # if playersConnected % 2 == 0 and userInRoom(nftNo) == False:
    if playersConnected % 2 == 0:
        room = getActiveGames().find_one({"_id": ROOMCOUNT - 1})
        opposingPlayer = getOtherPlayerInRoom(room, nftNo)
        currentPlayer = getOtherPlayerInRoom(room, opposingPlayer['nftNo'])
        roomData = {
            currentPlayer['socketId']: {"myScore": '', "opponentScore": "",
                                        "nftNo": opposingPlayer['nftNo'],
                                        "totalWins": opposingPlayer['stats']["totalWins"],
                                        "totalBetted": opposingPlayer['stats']["totalBetted"]
                                        },
            opposingPlayer['socketId']: {"myScore": '', "opponentScore": "",
                                         "nftNo": currentPlayer['nftNo'],
                                         "totalWins": currentPlayer['stats']["totalWins"],
                                         "totalBetted": currentPlayer['stats']["totalBetted"]
                                         },

            "betSize": room['betSize']
        }
        socket_manager.enter_room(socketId, ROOMCOUNT - 1)
        await socket_manager.emit('startGame', data=roomData, room=ROOMCOUNT - 1)


def userInRoom(nftNo):
    results = list(getActiveGames().find())
    for i in results:
        if i.get("player1").get('nftNo') == nftNo or i.get("player2").get('nftNo') == nftNo:
            return True
    return False


def getOtherPlayerInRoom(room, nftNo):
    if str(room['player2']['nftNo']) == str(nftNo):
        return getUser(room['player1']['nftNo'])
    if str(room['player1']['nftNo']) == str(nftNo):
        return getUser(room['player2']['nftNo'])


def getPlayerFromSocketIDANDROOM(room, socketId):
    if str(room['player2']['socketId']) == str(socketId):
        return 'player2'
    if str(room['player1']['socketId']) == str(socketId):
        return 'player1'


# two dbs maybe active rooms and old rooms
# filter rooms and see if there is any user with the same nft a room and dont match them if they are in one


async def roomResolution(result, roomData):
    if result == "draw":
        roomData.pop("playerChoices")
        roomData['player1']["notResponding"] = False
        roomData['player2']["notResponding"] = False
        roomData['player1']["timestamp"] = 0
        roomData['player2']["timestamp"] = 0

        getActiveGames().replace_one({"_id": roomData['_id']}, roomData)
    else:
        if result == "house":
            await updateLoser(roomData.get('player1').get('socketId'), roomData.get('player1')['nftNo'], roomData['betSize'])
            await updateLoser(roomData.get('player2').get('socketId'), roomData.get('player2')['nftNo'], roomData['betSize'])
            # increase pending earnings with the betsize then return
            increasePendingEarnings(roomData['betSize'])
            # close GAME
            closeThisRoom(roomData)
            await socket_manager.emit('endRoom', room=roomData['nonce'])
            await socket_manager.close_room(roomData['nonce'])
            return None

        if result == roomData.get('player1').get('socketId'):
            winner = roomData.get('player1')
            loser = roomData.get('player2')
            roomData['score'] = roomData['score'] + '1'

        elif result == roomData.get('player2').get('socketId'):
            winner = roomData.get('player2')
            loser = roomData.get('player1')
            roomData['score'] = roomData['score'] + '0'

        await updateWinner(winner['socketId'], winner['nftNo'], roomData['betSize'])
        await updateLoser(loser['socketId'], loser['nftNo'], roomData['betSize'])
        # update the data with the newscore
        getActiveGames().replace_one({"_id": roomData['_id']}, roomData)
        # closeRoom(roomData, result, winner['nftNo'])

        # emit end room to quit room on frontend

        # await socket_manager.emit('endRoom', room=roomData['nonce'])
    # await socket_manager.emit('roundEnded',room=roomData['nonce'])
    # kick everyone out of the room

    # TODO ALLOW USERS TO REMATCH
    #  await socket_manager.close_room(roomData['nonce'])
    # save room to db and increase room nonce
    # await socket_manager.emit('endRoom', room=roomData['nonce'])
    # close the room and kick them back to the lobby and archive the room

    # do something with data and end room
    # winner id is the result
    # give credits to user


async def roomResolutionDisconnect(result, roomData, nftNo):
    if result == roomData.get('player1').get('socketId'):
        winner = roomData.get('player2')
        loser = roomData.get('player1')

    elif result == roomData.get('player2').get('socketId'):
        winner = roomData.get('player1')
        loser = roomData.get('player2')

    await updateWinner(winner['socketId'], winner['nftNo'], roomData['betSize'])
    await updateLoser(loser['socketId'], loser['nftNo'], roomData['betSize'])
    closeRoom(roomData, result, winner['nftNo'])
    # emit end room to quit room on frontend

    await socket_manager.emit('endRoom', room=roomData['nonce'])
    # kick everyone out of the room
    opposingPlayer = getOtherPlayerInRoom(roomData, nftNo)
    await socket_manager.emit('Error', data="Other Player Quit The Game", to=opposingPlayer['socketId'])
    await socket_manager.close_room(roomData['nonce'])
    # save room to db and increase room nonce
    # await socket_manager.emit('endRoom', room=roomData['nonce'])
    # close the room and kick them back to the lobby and archive the room

    # do something with data and end room
    # winner id is the result
    # give credits to user


# handle choice uses room mapping so we need to now also use the db
async def handleChoice(socketId, choice, nftNo, jwtToken):
    if securityCheck(socketId, jwtToken) != True:
        return None
    # ROOMSTATUS[ROOMMAPPING[socketId]]
    Roomdata = getRoomFromSocketId(socketId)
    if Roomdata.get('playerChoices'):
        if not Roomdata['playerChoices'].get(socketId):
            Roomdata.get('playerChoices')[socketId] = {
                "socketId": socketId, "choice": choice}
            Roomdata.get('playerChoices')["1"] = {
                "socketId": socketId, "choice": choice}
            player = getPlayerFromSocketIDANDROOM(Roomdata, socketId)
            getActiveGames().replace_one({"_id": Roomdata['_id']}, Roomdata)
            # winnerSocketID
            result = calulateWinner(Roomdata['playerChoices']["0"],
                                    Roomdata['playerChoices']["1"])
            # TODO Send the each user the choice of the other user for the animation

            res = {"result": result,
                   Roomdata['playerChoices']['1']['socketId']: Roomdata['playerChoices']["0"]['choice'],
                   Roomdata['playerChoices']['0']['socketId']: Roomdata['playerChoices']['1']['choice']
                   }

            await socket_manager.emit('result', data=res, room=Roomdata['nonce'])

            await roomResolution(result, Roomdata)
            # HERE ADD CHECK TO SEE IF THE CHOICES WERE NOT REVEALED TO END THE GAME
            if Roomdata['playerChoices']["0"]['choice'] == "notrevealed" or Roomdata['playerChoices']["1"]['choice'] == "notrevealed":
                closeThisRoom(Roomdata)
                await socket_manager.emit('endRoom', room=Roomdata['nonce'])
                await socket_manager.close_room(Roomdata['nonce'])
                return None
    else:
        playerChoices = {}
        playerChoices[socketId] = {"socketId": socketId, "choice": choice}
        playerChoices["0"] = {"socketId": socketId, "choice": choice}
        Roomdata['playerChoices'] = playerChoices
        player = getPlayerFromSocketIDANDROOM(Roomdata, socketId)
        # HERE
        opposingPlayer = getOtherPlayerInRoom(Roomdata, nftNo)

        #currentPlayer = getOtherPlayerInRoom(room, opposingPlayer['nftNo'])
        # opposingPlayer=getOtherPlayerInRoom(Roomdata,player)
        Roomdata[player]["notResponding"] = False
        Roomdata[player]["timestamp"] = 0
        getActiveGames().replace_one({"_id": Roomdata['_id']}, Roomdata)

        await socket_manager.emit("playerChoiceMade", to=opposingPlayer['socketId'])


# big problem with rooms is that right now they are just based on incrementation
# need to program it in a way that it has a good infrastruction but no i will work on the coins


def getRoomFromSocketId(socketId):
    results = list(getActiveGames().find())
    for i in results:
        if i.get("player1").get('socketId') == socketId:
            return i
        if i.get("player2").get('socketId') == socketId:
            return i


async def handleDisconnection(socketId):
    try:
        user = getUserBySocketId(socketId)
        if user != None:
            setAccountOffline(socketId)
            if userInRoom(user['nftNo']):
                room = getRoomFromSocketId(socketId)
                await roomResolutionDisconnect(socketId, room, user['nftNo'])
                closeThisRoom(room)
    except Exception as e:
        print(e)

    # global ROOMCOUNT
    # global playersConnected
    # playersConnected -= 1
    # if playersConnected % 2 == 0:
    #     ROOMCOUNT -= 1
    # print('PLAYERS CONNECTED ' + str(playersConnected))
    # print('ROOMS ' + str(playersConnected))


async def handlesignIn(socketId, signedMessage, nftNo, address):
    # TODO IMPLEMENT ACTIVE IN USER TO ALWAYS KEEP TRACK OF PEOPLE USING THE GAME RN AND ONLY ALOWING SOMEONE TO USE ONE PC
    if getUserDb().find_one({"nftNo": nftNo}) != None:
        user = getUserDb().find_one({"nftNo": nftNo})
        tokenId = tokenNoToId(nftNo)
        tokenOnwership = doesOwnToken(address, tokenId)
        if user['active'] == True:
            await socket_manager.emit('Error', 'You Are Already Logged In on another session.',
                                      to=socketId)
            return None
        if tokenOnwership == False:
            await socket_manager.emit('Error', "You Don't Own This NFT.",
                                      to=socketId)
            return
        if user['signedMessage'] == signedMessage and tokenOnwership == True:
            user['accessToken'] = generateJWTTOKEN(socketId, nftNo)
            user['active'] = True
            user['socketId'] = socketId
            user['address'] = address
            user['signedMessage'] = signedMessage
            getUserDb().replace_one({"nftNo": nftNo}, user)
            setAccountOnline(socketId)
            userData = userFromRecord(user)
            await socket_manager.emit('userInfo', userData, to=socketId)
            return None

    w3 = Web3(Web3.HTTPProvider(HTTP_PROVIDER))
    message = encode_defunct(
        text="I Agree to Login to HotDogFace Rock Paper Scissors. I Love My HotDogFace #" + nftNo)
    messageAccount = w3.eth.account.recover_message(
        message, signature=signedMessage)
    message = encode_defunct(
        text=signedMessage)
    tokenId = tokenNoToId(nftNo)
    tokenOnwership = doesOwnToken(address, tokenId)
    if tokenOnwership == False:
        await socket_manager.emit('Error', "You Don't Own This NFT.",
                                  to=socketId)
        return
    if messageAccount == address and tokenOnwership == True:
        # TODO GENERATE JWT
        createAccount(address, tokenId, nftNo, signedMessage,
                      socketId, generateJWTTOKEN(socketId, nftNo))
        userData = userFromRecord(getUserDb().find_one({"nftNo": nftNo}))
        await socket_manager.emit('userInfo', userData, to=socketId)


# async def handleLogin(socketId, signedMessage, nftNo, address):
#     # TODO check if user still owns the token
#     user = getUser(nftNo)
#     if user != None:
#         if doesOwnToken(user['address'], user['nftID']) == True:
#             user['socketId'] = socketId
#             user['active'] = True
#             getUserDb().replace_one({"nftNo": nftNo}, user)
#             userData = userFromRecord(user)
#             if userData['signedMessage'] == signedMessage:
#                 await socket_manager.emit('userInfo', userData, to=socketId)
#

def userFromRecord(userData):
    user = {'accessToken': userData["accessToken"],
            "nftNo": userData["nftNo"],
            "nftID": userData["nftID"],
            "address": userData["address"],
            "signedMessage": userData["signedMessage"],
            "totalUnpaid": userData["totalUnpaid"],
            "stats": userData["stats"], "balance": userData["balance"]}
    return user


async def handleReadyToPlay(socketId, nftNo, betSize, jwtToken):
    if securityCheck(socketId, jwtToken) != True:
        return None
    await roomManager(socketId, nftNo, betSize)


async def handleCancelReadyToPlay(socketId, nftNo, jwtToken):
    if securityCheck(socketId, jwtToken) != True:
        return None
    # HAPPENS IF USER IS LOOKING TO PLAY A GAME BUT CANCELS CUZ THERE IS NO ONE
    global playersConnected
    playersConnected -= 1
    if playersConnected % 2 == 0:
        # TODO KILL THE ROOM
        room = getRoomFromSocketId(socketId)
        closeThisRoom(room)
    print('PLAYERS CONNECTED ' + str(playersConnected))
    print('ROOMS ' + str(getRoomCount()))


async def processUserNotResponding(socketId):
    room = getRoomFromSocketId(socketId)
    player = getPlayerFromSocketIDANDROOM(room, socketId)
    # timeinseconds
    # switch user to get other user
    oppositePlayer = getOppositePlayerTag(player)
    timestamp = int(time.time())
    room[oppositePlayer]["notResponding"] = True
    room[oppositePlayer]['timestamp'] = timestamp
    getActiveGames().replace_one({"_id": room['_id']}, room)
    # emit start end CountDown


def getOppositePlayerTag(player):
    if player == 'player1':
        return 'player2'
    if player == 'player2':
        return 'player1'


async def assertUserNotResponding(socketId):
    # end the game becasue other user timedout
    room = getRoomFromSocketId(socketId)
    player = getPlayerFromSocketIDANDROOM(room, socketId)
    # switch user to get other user
    oppositePlayer = getOppositePlayerTag(player)
    if room[oppositePlayer]['notResponding'] == True and int(time.time()) >= room[oppositePlayer][
            'timestamp'] + ROOMTIMEOUT and room.get('playerChoices') != None:
        await roomResolutionDisconnect(room[oppositePlayer]['socketId'], room)


async def processInitRaiseBet(socketId, nftNo, newBet, jwtToken):
    if securityCheck(socketId, jwtToken) != True:
        return None
    # check if both users have enough balance
    # lock user balances so we can make sure nothing weird happens
    room = getRoomFromSocketId(socketId)
    player = getUserBySocketId(socketId)
    otherPlayer = getOtherPlayerInRoom(room, nftNo)
    if player['balance'] < (int(newBet)) or otherPlayer['balance'] < (int(newBet)):
        await socket_manager.emit('Error', 'Both parties need to have enough tokens for you to raise the bet',
                                  to=socketId)
        return
    room['betRaiseProposed'] = True
    room['betRaiseAmount'] = int(newBet)
    getActiveGames().replace_one({"_id": room['_id']}, room)
    await socket_manager.emit('betRaiseProposal', newBet, to=otherPlayer['socketId'])


async def raiseGameBet(socketId, nftNo, jwtToken):
    if securityCheck(socketId, jwtToken) != True:
        return None
    # Todo fix
    room = getRoomFromSocketId(socketId)
    room['betRaised'] = True
    room['betRaiseProposed'] = False
    # set betSize to new bet amount
    room['betSize'] = room['betRaiseAmount']
    room['betRaiseAmount'] = 0
    opposingPlayer = getOtherPlayerInRoom(room, nftNo)
    currentPlayer = getOtherPlayerInRoom(room, opposingPlayer['nftNo'])
    if currentPlayer['socketId'] == room['player1']['socketId']:
        currentPlayerScore = room['score']
        otherPlayerScore = reverseScore(room['score'])
    elif currentPlayer['socketId'] == room['player2']['socketId']:
        currentPlayerScore = reverseScore(room['score'])
        otherPlayerScore = room['score']
    roomData = {
        currentPlayer['socketId']: {
            'myScore': currentPlayerScore,
            'opponentScore': otherPlayerScore,
            "nftNo": opposingPlayer['nftNo'],
            "totalWins": opposingPlayer['stats']["totalWins"],
            "totalBetted": opposingPlayer['stats']["totalBetted"]
        }, opposingPlayer['socketId']: {
            'myScore': otherPlayerScore,
            'opponentScore': currentPlayerScore,
            "nftNo": currentPlayer['nftNo'],
            "totalWins": currentPlayer['stats']["totalWins"],
            "totalBetted": currentPlayer['stats']["totalBetted"]
        },
        "betSize": room['betSize']
    }
    getActiveGames().replace_one({"_id": room['_id']}, room)
    await socket_manager.emit('betRaised', roomData, room=room['_id'])


async def betRaiseRefusedReset(socketId, nftNo, jwtToken):
    if securityCheck(socketId, jwtToken) != True:
        return None
    room = getRoomFromSocketId(socketId)
    room['betRaised'] = False
    room['betRaiseProposed'] = False
    room['betRaiseAmount'] = 0
    getActiveGames().replace_one({"_id": room['_id']}, room)
    await socket_manager.emit('betNotRaised', room, room=room['_id'])


def cleanUserForLEADERBOARD(_user):
    user = {'stats': {
        'totalWins': _user['stats']['totalWins'],
        'totalBetted': _user['stats']['totalBetted'],
    },
        'nftNo': _user['nftNo']}
    return user


async def getLeaderBoard(socketId, jwtToken):
    if securityCheck(socketId, jwtToken) != True:
        return None
    users = [cleanUserForLEADERBOARD(user) for user in getUserDb().find()]
    await socket_manager.emit('leaderBoardData', users, to=socketId)


async def handleRematch(socketId, choice, nftNo, jwtToken):
    if securityCheck(socketId, jwtToken) != True:
        return None
    # TODO CHECK THAT USERS HAVE ENOUGH MONEY  / 5 tokens to buy in for table

    if choice == "true":
        room = getRoomFromSocketId(socketId)
        if room["rematchProposed"]["state"] == False:
            # if rematch is not proposed we set it to true
            # TODO GET USER AND CHECK HE HAS ENOUGH BALANCE OR SEND ERROR AND END ROOM
            user = getUserBySocketId(socketId)
            if user['balance'] >= 5:
                room["rematchProposed"] = {
                    "state": True, "initsocket": socketId}
                getActiveGames().replace_one({"_id": room['_id']}, room)
            else:
                await socket_manager.emit('Error', "You Don't Own Enough Tokens For A Rematch", to=socketId)
                closeThisRoom(room)
                await socket_manager.emit('endRoom', room=room['nonce'])
                opposingPlayer = getOtherPlayerInRoom(room, nftNo)
                await socket_manager.emit('Error', data="Other Player Doesn't Have Enough Tokens For A Rematch.", to=opposingPlayer['socketId'])
                await socket_manager.close_room(room['nonce'])
        elif room["rematchProposed"]["state"] == True and room["rematchProposed"]["initsocket"] != '' and \
                room["rematchProposed"]["initsocket"] != socketId:
            user = getUserBySocketId(socketId)
            if user['balance'] >= 5:
                room.pop("playerChoices")
                room['player1']["notResponding"] = False
                # reset bet size to normal
                room['betSize'] = 5
                room['player2']["notResponding"] = False
                room['player1']["timestamp"] = 0
                room['player2']["timestamp"] = 0
                room["rematchProposed"]['state'] = False
                room['betRaised'] = False
                getActiveGames().replace_one({"_id": room['_id']}, room)
                opposingPlayer = getOtherPlayerInRoom(room, nftNo)
                currentPlayer = getOtherPlayerInRoom(
                    room, opposingPlayer['nftNo'])
                if currentPlayer['socketId'] == room['player1']['socketId']:
                    currentPlayerScore = room['score']
                    otherPlayerScore = reverseScore(room['score'])
                elif currentPlayer['socketId'] == room['player2']['socketId']:
                    currentPlayerScore = reverseScore(room['score'])
                    otherPlayerScore = room['score']
                roomData = {
                    currentPlayer['socketId']: {
                        'myScore': currentPlayerScore,
                        'opponentScore': otherPlayerScore,
                        "nftNo": opposingPlayer['nftNo'],
                        "totalWins": opposingPlayer['stats']["totalWins"],
                        "totalBetted": opposingPlayer['stats']["totalBetted"]
                    }, opposingPlayer['socketId']: {
                        'myScore': otherPlayerScore,
                        'opponentScore': currentPlayerScore,
                        "nftNo": currentPlayer['nftNo'],
                        "totalWins": currentPlayer['stats']["totalWins"],
                        "totalBetted": currentPlayer['stats']["totalBetted"]
                    },
                    "betSize": room['betSize']
                }
                await socket_manager.emit('startGame', data=roomData, room=room['nonce'])
            else:
                await socket_manager.emit('Error', "You Don't Own Enough Tokens For A Rematch", to=socketId)
                closeThisRoom(room)

                await socket_manager.emit('endRoom', room=room['nonce'])
                opposingPlayer = getOtherPlayerInRoom(room, nftNo)
                await socket_manager.emit('Error', data="Other Player Quit The Game", to=opposingPlayer['socketId'])
                await socket_manager.close_room(room['nonce'])
    else:
        room = getRoomFromSocketId(socketId)
        closeThisRoom(room)
        await socket_manager.emit('endRoom', room=room['nonce'])
        opposingPlayer = getOtherPlayerInRoom(room, nftNo)
        await socket_manager.emit('Error', data="Other Player Quit The Game", to=opposingPlayer['socketId'])
        await socket_manager.close_room(room['nonce'])


socket_manager.on('rematch', handleRematch)
socket_manager.on('deposit', processUserDeposit)
socket_manager.on('readyToPlay', handleReadyToPlay)
socket_manager.on('connect', handleConnection)
socket_manager.on('signInToServer', handlesignIn)
# socket_manager.on('loginInToServer', handleLogin) RETIRED
socket_manager.on('cancelReadyToplay', handleCancelReadyToPlay)
socket_manager.on('disconnect', handleDisconnection)
socket_manager.on('choiceMade', handleChoice)
socket_manager.on('withdraw', processUserWithdraw)
#socket_manager.on('userNotResponding', processUserNotResponding)
#socket_manager.on('userNotRespondingResolution', assertUserNotResponding)
socket_manager.on('initRaiseBet', processInitRaiseBet)
socket_manager.on('betRaiseAccepted', raiseGameBet)
socket_manager.on('betRaiseRefused', betRaiseRefusedReset)
socket_manager.on('getLeaderBoard', getLeaderBoard)
socket_manager.on('buy', processUserBuy)

# twoo functions

# ROOM ID == TABLE ID TO MAKE IT SIMPLE WE WILL USE A COUNTER TO ALSO IDENTIFY THE AMOUNT OF ROOMS
# we need it to ways one where you can join me in a room with a link
# or by just joining random rooms to play

if __name__ == "__main__":
    client.drop_database('HDF')
    client.drop_database('Games')
    resetGames()
    initStatsDb()
    uvicorn.run("server:app", port=8000, reload=True)

# custom bet size
