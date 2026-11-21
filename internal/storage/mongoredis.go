// Package storage provides durable MongoDB job storage with Redis read-through cache.
// MongoDB is authoritative. Redis failure never loses the durable job record.
package storage

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"sort"
	"time"

	"github.com/redis/go-redis/v9"
	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"github.com/marck0820001/peru-budget-distributed.git/internal/api"
)

const cacheTTL = 60 * time.Second
const cachePrefix = "perubudget:pc4:job:"

type mongoRecord struct {
	ID        string    `bson:"_id"`
	Payload   string    `bson:"payload"`
	Status    string    `bson:"status"`
	StartedAt time.Time `bson:"started_at"`
}

type MongoRedis struct {
	client *mongo.Client
	col    *mongo.Collection
	redis  *redis.Client
}

func NewMongoRedis(ctx context.Context, mongoURI, dbName, redisAddr string) (*MongoRedis, error) {
	if mongoURI == "" || dbName == "" || redisAddr == "" {
		return nil, errors.New("MongoDB y Redis son obligatorios")
	}
	client, err := mongo.Connect(options.Client().ApplyURI(mongoURI).SetServerSelectionTimeout(5 * time.Second))
	if err != nil {
		return nil, fmt.Errorf("crear cliente MongoDB: %w", err)
	}
	if err := client.Ping(ctx, nil); err != nil {
		_ = client.Disconnect(context.Background())
		return nil, fmt.Errorf("ping MongoDB: %w", err)
	}
	redisClient := redis.NewClient(&redis.Options{Addr: redisAddr, DialTimeout: 2 * time.Second, ReadTimeout: 2 * time.Second, WriteTimeout: 2 * time.Second})
	if err := redisClient.Ping(ctx).Err(); err != nil {
		_ = redisClient.Close()
		_ = client.Disconnect(context.Background())
		return nil, fmt.Errorf("ping Redis: %w", err)
	}
	return &MongoRedis{client: client, col: client.Database(dbName).Collection("training_jobs"), redis: redisClient}, nil
}
func (s *MongoRedis) Close() error {
	e1 := s.redis.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	e2 := s.client.Disconnect(ctx)
	return errors.Join(e1, e2)
}

func (s *MongoRedis) Put(ctx context.Context, job api.Job) error {
	payload, err := json.Marshal(job)
	if err != nil {
		return fmt.Errorf("codificar job: %w", err)
	}
	// UpdateOne with upsert guarantees repeated state transitions remain idempotent.
	// MongoDB is written before any cache update.
	_, err = s.col.UpdateOne(ctx, bson.D{{Key: "_id", Value: job.ID}}, bson.D{{Key: "$set", Value: bson.D{
		{Key: "payload", Value: string(payload)},
		{Key: "status", Value: job.Status},
		{Key: "started_at", Value: job.StartedAt},
	}}}, options.UpdateOne().SetUpsert(true))
	if err != nil {
		return fmt.Errorf("MongoDB guardar job %s: %w", job.ID, err)
	}
	// Redis is a performance optimization; cache failures are logged but non-fatal.
	if err := s.redis.Set(ctx, cachePrefix+job.ID, string(payload), cacheTTL).Err(); err != nil {
		log.Printf("WARN: cache Redis job %s: %v", job.ID, err)
		// Remove old data if possible; MongoDB remains authoritative.
		_ = s.redis.Del(ctx, cachePrefix+job.ID).Err()
	}
	return nil
}

func (s *MongoRedis) Get(ctx context.Context, id string) (api.Job, bool, error) {
	var result api.Job
	if id == "" {
		return result, false, nil
	}
	if value, err := s.redis.Get(ctx, cachePrefix+id).Result(); err == nil {
		if json.Unmarshal([]byte(value), &result) == nil && result.ID == id {
			return result, true, nil
		}
		_ = s.redis.Del(ctx, cachePrefix+id).Err()
	}
	var record mongoRecord
	err := s.col.FindOne(ctx, bson.D{{Key: "_id", Value: id}}).Decode(&record)
	if errors.Is(err, mongo.ErrNoDocuments) {
		return result, false, nil
	}
	if err != nil {
		return result, false, fmt.Errorf("MongoDB consultar job: %w", err)
	}
	if err = json.Unmarshal([]byte(record.Payload), &result); err != nil {
		return result, false, fmt.Errorf("MongoDB payload corrupto: %w", err)
	}
	if result.ID != id {
		return api.Job{}, false, errors.New("id inconsistente en MongoDB")
	}
	// Best effort: cache jobs for a bounded time.
	_ = s.redis.Set(ctx, cachePrefix+id, record.Payload, cacheTTL).Err()
	return result, true, nil
}
func (s *MongoRedis) List(ctx context.Context) ([]api.Job, error) {
	cursor, err := s.col.Find(ctx, bson.D{})
	if err != nil {
		return nil, fmt.Errorf("MongoDB listar jobs: %w", err)
	}
	defer cursor.Close(ctx)
	rows := []api.Job{}
	for cursor.Next(ctx) {
		var record mongoRecord
		if err := cursor.Decode(&record); err != nil {
			return nil, err
		}
		var j api.Job
		if err := json.Unmarshal([]byte(record.Payload), &j); err != nil {
			return nil, fmt.Errorf("payload MongoDB invalidado: %w", err)
		}
		rows = append(rows, j)
	}
	if err := cursor.Err(); err != nil {
		return nil, err
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].StartedAt.After(rows[j].StartedAt) })
	return rows, nil
}
func (s *MongoRedis) Health(ctx context.Context) map[string]string {
	state := map[string]string{"mongodb": "ok", "redis": "ok"}
	if err := s.client.Ping(ctx, nil); err != nil {
		state["mongodb"] = "error: " + err.Error()
	}
	if err := s.redis.Ping(ctx).Err(); err != nil {
		state["redis"] = "error: " + err.Error()
	}
	return state
}
